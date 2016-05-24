from django.core.exceptions import ValidationError
from django.utils.encoding import smart_str

from rest_framework import serializers
from bson.errors import InvalidId
from bson import DBRef, ObjectId

import numbers
import inspect
import json

from mongoengine.dereference import DeReference
from mongoengine.base.document import BaseDocument
from mongoengine.document import Document, EmbeddedDocument
from mongoengine.fields import ObjectId
from mongoengine.base import get_document, _document_registry
from mongoengine.errors import NotRegistered

from collections import OrderedDict

from mongoengine import fields as me_fields
from rest_framework import fields as drf_fields
from rest_framework.relations import HyperlinkedIdentityField
from rest_framework.fields import get_attribute, SkipField, empty
from rest_framework.utils import html
from rest_framework.utils.serializer_helpers import BindingDict

from rest_framework_mongoengine.utils import get_field_info, PolymorphicChainMap

class DocumentField(serializers.Field):
    """
    Base field for Mongoengine fields that we can not convert to DRF fields.

    To Users:
        - You can subclass DocumentField to implement custom (de)serialization
    """

    type_label = 'DocumentField'

    def __init__(self, *args, **kwargs):

        self.depth = kwargs.pop('depth')
        self.ignore_depth = False  # set this from a kwarg!
        try:
            self.model_field = kwargs.pop('model_field')
        except KeyError:
            raise ValueError("%s requires 'model_field' kwarg" % self.type_label)

        # better hotwire.
        self.dereference_refs = False

        super(DocumentField, self).__init__(*args, **kwargs)

    @property
    def fields(self):
        """
        A dictionary of {field_name: field_instance}.
        """
        # `fields` is evaluated lazily. We do this to ensure that we don't
        # have issues importing modules that use ModelSerializers as fields,
        # even if Django's app-loading stage has not yet run.
        if not hasattr(self, '_fields'):
            self._fields = BindingDict(self)
            for key, value in self.get_fields().items():
                self._fields[key] = value
        return self._fields

    def get_fields(self):
        #handle dynamic/dict fields
        raise NotImplementedError("Fields subclassing DocumentField need to implement get_fields.")

    def get_document_subfields(self, model):
        model_fields = model._fields
        fields = {}
        for field_name in model_fields:
            fields[field_name] = self.get_subfield(model_fields[field_name])
        return fields

    def get_subfield(self, model_field):
        kwargs = self.get_field_kwargs(model_field)
        return self.get_field_mapping(model_field)(**kwargs)

    def get_base_kwargs(self):
        return self.parent.get_base_kwargs()

    def get_field_kwargs(self, subfield):
        """
        Get kwargs that will be used for validation/serialization
        """
        kwargs = self.parent.get_base_kwargs()

        #kwargs to pass to all drfme fields
        #this includes lists, dicts, embedded documents, etc
        #depth included for flow control during recursive serialization.
        if self.is_drfme_field(subfield):
            kwargs['model_field'] = subfield
            kwargs['depth'] = self.depth - 1

        if type(subfield) is me_fields.ObjectIdField:
            kwargs['required'] = False
        else:
            kwargs['required'] = subfield.required

        if subfield.default:
            kwargs['required'] = False
            kwargs['default'] = subfield.default

        attribute_dict = {
            me_fields.StringField: ['max_length'],
            me_fields.DecimalField: ['min_value', 'max_value'],
            me_fields.EmailField: ['max_length'],
            me_fields.FileField: ['max_length'],
            me_fields.URLField: ['max_length'],
            me_fields.BinaryField: ['max_bytes']
        }

        #append any extra attributes based on the dict above, as needed.
        if subfield.__class__ in attribute_dict:
            attributes = attribute_dict[subfield.__class__]
            for attribute in attributes:
                if hasattr(subfield, attribute):
                    kwargs.update({attribute: getattr(subfield, attribute)})

        return kwargs

    def go_deeper(self, is_ref=False):
        #true if we should go deeper in subfields or not.
        if is_ref:
            return self.depth and self.dereference_refs
        else:
            return self.depth or self.ignore_depth

    def get_field_mapping(self, field):
        #query parent to get field mapping.
        #Since this is implemented in the serializer and in DocumentField
        #we'll pass this up the chain until we get to the serializer, where it can be easily configured.
        assert hasattr(self, 'parent'), (
            "%s Field has no parent attribute"
            "field.bind probably did not get called." %
            (self.field_name)
        )

        return self.parent.get_field_mapping(field)

    def is_drfme_field(self, field):
        #query parent to get field mapping.
        #Since this is implemented in the serializer and in DocumentField
        #we'll pass this up the chain until we get to the serializer, where it can be easily configured.
        assert hasattr(self, 'parent'), (
            "%s Field has no parent attribute"
            "field.bind probably did not get called." %
            (self.field_name)
        )

        return self.parent.is_drfme_field(field)

    def to_internal_value(self, data):
        return self.model_field.to_python(data)

    def to_representation(self, value):
        #transform_object(obj, depth)
        #We don't really ever want to hit this case, in theory.
        return smart_str(value) if isinstance(value, ObjectId) else value

class ReferenceField(DocumentField):
    """
    For ReferenceField.
    We always dereference DBRef object before serialization
    TODO: Maybe support DBRef too?
    """

    type_label = 'ReferenceField'

    def __init__(self, *args, **kwargs):
        super(ReferenceField, self).__init__(*args, **kwargs)

        self.model_cls = self.model_field.document_type

    def get_fields(self):
        #return fields for all the subfields in this document.
        #if we need to parse deeper, build a list of the child document's fields.
        if self.go_deeper(is_ref=True):
            return self.get_document_subfields(self.model_cls)
        return {}

    def to_internal_value(self, data):
        try:
            dbref = self.model_field.to_python(data)
        except InvalidId:
            raise ValidationError(self.error_messages['invalid_dbref'])

        return dbref


    def get_attribute(self, instance):
        #need to overwrite this, since drf's version
        #will call get_attr(instance, field_name), which dereferences ReferenceFields
        #even if we don't need them. We need it to be mindful of depth.
        if self.go_deeper(is_ref=True):
            #TODO: fix to iterate properly?
            return super(DocumentField, self).get_attribute(instance)

        #return dbref by grabbing data directly, instead of going through the ReferenceField's __get__ method
        return instance._data[self.source]



    def to_representation(self, value):
        #value is either DBRef (if we're out of depth)
        #else a MongoEngine model reference.

        if value is None:
            return None

        if self.go_deeper(is_ref=True):
            #get model's fields
            #if go_deeper returns true, we've already dereferenced this in get_attribute.
            ret = OrderedDict()
            for field_name in value._fields:
                ret[field_name] = self.fields[field_name].to_representation(getattr(value, field_name))
            return ret
        elif isinstance(value, (DBRef, Document)):
            #don't want to go deeper, and have either a DBRef or a document
            #we'll have a document on POSTs/PUTs, or if something else has dereferenced it for us.
            return smart_str(value.id)
        else:
            return smart_str(value)



class ListField(DocumentField):

    type_label = 'ListField'

    def get_fields(self):
        #instantiate the nested field
        nested_field_instance = self.model_field.field
        #initialize field
        return {
            self.model_field.name: self.get_subfield(nested_field_instance)
        }

    def get_value(self, dictionary):
        # We override the default field access in order to support
        # lists in HTML forms.
        if html.is_html_input(dictionary):
            return html.parse_html_list(dictionary, prefix=self.field_name)
        value = dictionary.get(self.field_name, empty)
        #if isinstance(value, type('')):
        #    return json.loads(value)
        return value

    def to_internal_value(self, data):
        """
        List of dicts of native values <- List of dicts of primitive datatypes.
        """

        serializer_field = self.fields[self.model_field.name]

        if html.is_html_input(data):
            data = html.parse_html_list(data)
        if isinstance(data, type('')) or not hasattr(data, '__iter__'):
            self.fail('not_a_list', input_type=type(data).__name__)
        return [serializer_field.run_validation(item) for item in data]

    def get_attribute(self, instance):
        #since this is a passthrough, be careful about dereferencing the contents.
        serializer_field = self.fields[self.model_field.name]
        if not self.dereference_refs and isinstance(serializer_field, ReferenceField):
            #return data by grabbing it directly, instead of going through the field's __get__ method
            return instance._data[self.source]
        return super(DocumentField, self).get_attribute(instance)


    def to_representation(self, value):
        serializer_field = self.fields[self.model_field.name]
        return [serializer_field.to_representation(v) for v in value]


class MapField(ListField):
    type_label = "MapField"

    def to_internal_value(self, data):
        """
        List of dicts of native values <- List of dicts of primitive datatypes.
        """

        serializer_field = self.fields[self.model_field.name]

        if html.is_html_input(data):
            data = html.parse_html_list(data)
        if isinstance(data, type('')) or not hasattr(data, '__iter__'):
            self.fail('not_a_dict', input_type=type(data).__name__)

        native = OrderedDict()
        for key in data:
            native[key] = serializer_field.run_validation(data[key])
        return native

    def to_representation(self, value):
        serializer_field = self.fields[self.model_field.name]

        ret = OrderedDict()
        for key in value:
            ret[key] = serializer_field.to_representation(value[key])
        return ret

class EmbeddedDocumentField(DocumentField):

    type_label = 'EmbeddedDocumentField'

    def __init__(self, *args, **kwargs):
        super(EmbeddedDocumentField, self).__init__(*args, **kwargs)

        self.document_type = self.model_field.document_type

    def get_fields(self):
        #if we need to recurse deeper, build a list of the embedded document's fields.
        if self.go_deeper():
            return self.get_document_subfields(self.document_type)
        return {}

    def get_attribute(self, instance):
        if self.go_deeper():
            return instance[self.source]

        else:
            raise Exception("SerializerField %s ran out of depth serializing instance: %s, on field %s" % (self, instance, self.model_field.field_name))


    def to_representation(self, value):
        if value is None:
            return None
        elif self.go_deeper():
            #get model's fields
            ret = OrderedDict()
            for field_name in self.fields:
                if value._data[field_name] is None:
                    ret[field_name] = None
                else:
                    ret[field_name] = self.fields[field_name].to_representation(value._data[field_name])
            return ret
        else:
            #should probably have a proper depth-specific error.
            raise Exception("SerializerField %s ran out of depth serializing instance: %s, on field %s" % (self, value, self.model_field.name))

    def to_internal_value(self, data):
        return self.model_field.to_python(data)

class PolymorphicEmbeddedDocumentField(EmbeddedDocumentField):
    def __init__(self, *args, **kwargs):
        super(PolymorphicEmbeddedDocumentField, self).__init__(*args, **kwargs)
        self.chainmap = PolymorphicChainMap(self, None, self.document_type)


    def to_representation(self, value):
        cls = value.__class__
        fields = self.chainmap[cls]

        if value is None:
            return None
        elif self.go_deeper():
            #get model's fields
            ret = OrderedDict()
            for field_name in fields:
                if value._data[field_name] is None:
                    ret[field_name] = None
                else:
                    ret[field_name] = fields[field_name].to_representation(value._data[field_name])
            return ret
        else:
            #should probably have a proper depth-specific error.
            raise Exception("SerializerField %s ran out of depth serializing instance: %s, on field %s" % (self, value, self.model_field.name))


class DynamicField(DocumentField):

    type_label = 'DynamicField'
    serializers = {}

    def __init__(self, field_name=None, source=None, *args, **kwargs):
        super(DynamicField, self).__init__(*args, **kwargs)
        self.field_name = field_name
        self.source = source
        if source:
            self.source_attrs = self.source.split('.')

    def get_attribute(self, instance):
        return instance._data[self.source]

    def to_representation(self, value):

        if isinstance(value, (DBRef, Document)):
            #Will not get DBRefs thanks to how MongoEngine handles DynamicFields
            #but, respect depth anyways.
            if self.go_deeper(is_ref=True):
                cls = type(value)
                if type(cls) not in self.serializers:
                    self.serializers[cls] = BindingDict(self)
                    for key, val in self.get_document_subfields(cls).items():
                        self.serializers[cls][key] = val
                fields = self.serializers[cls]

                ret = OrderedDict()
                for field in fields:
                    field_value = value._data[field]
                    ret[field] = fields[field].to_representation(field_value)
                return ret
            else:
                #out of depth
                return smart_str(value.id)
        elif isinstance(value, EmbeddedDocument):
            if self.go_deeper():
                cls = type(value)

                if type(cls) not in self.serializers:
                    self.serializers[cls] = BindingDict(self)
                    for key, val in self.get_document_subfields(cls).items():
                        self.serializers[cls][key] = val
                fields = self.serializers[cls]

                ret = OrderedDict()
                for field in fields:
                    field_value = value._data[field]
                    ret[field] = fields[field].to_representation(field_value)
                return ret
            else:
                #out of depth
                return "%s Object: Out of Depth" % type(value).__name__

        elif isinstance(value, ObjectId):
            return smart_str(value)

        elif isinstance(value, list):
            #list of things.
            #dyn = DynamicField(**self.get_field_kwargs(self.model_field))
            return [self.to_representation(i) for i in value]

        else:
            #some other type of value.
            if isinstance(value, numbers.Number):
                return value

            return value




class DictField(DocumentField):

    type_label = "DictField"
    serializers = {}

    def __init__(self, *args, **kwargs):
        super(DictField, self).__init__(*args, **kwargs)

    def get_attribute(self, instance):

        #return dict as provided by the instance.
        return instance._data[self.source]

    def to_representation(self, value):
        ret = OrderedDict()

        for key in value:
            item = value[key]

            if isinstance(item, DBRef):
                #DBRef, so this is a model.
                if self.go_deeper(is_ref=True):
                    #have depth, we must go deeper.
                    #serialize-on-the-fly! (patent pending)
                    item = DeReference()([item])[0]
                    cls = item.__class__
                    if type(cls) not in self.serializers:
                        self.serializers[cls] = BindingDict(self)
                        for key, val in self.get_document_subfields(cls).items():
                            self.serializers[cls][key] = val
                    fields = self.serializers[cls]

                    sub_ret = OrderedDict()
                    for field in fields:
                        field_value = item._data[field]
                        sub_ret[field] = fields[field].to_representation(field_value)
                    ret[key] = sub_ret
                else:
                    #no depth, so just pretty-print the dbref.
                    ret[key] = smart_str(item.id)
            elif isinstance(item, dict) and '_cls' in item and item['_cls'] in _document_registry:
                #has _cls, isn't a dbref, but is in the document registry - should be an embedded document.
                if self.go_deeper():
                    cls = get_document(item['_cls'])
                    #instantiate EmbeddedDocument object
                    item = cls._from_son(item)

                    #get serializer fields from cache, or make them if needed.
                    if type(cls) not in self.serializers:
                        self.serializers[cls] = BindingDict(self)
                        for key, val in self.get_document_subfields(cls).items():
                            self.serializers[cls][key] = val
                        fields = self.serializers[cls]

                    #iterate.
                    sub_ret = OrderedDict()
                    for field in fields:
                        field_value = item._data[field]
                        sub_ret[field] = fields[field].to_representation(field_value)
                    ret[key] = sub_ret

                else:
                    #no depth, just print the something representing the EmbeddedDocument.
                    cls = item['_cls']
                    ret[key] = "Embedded Document " + cls + " (out of depth)"
                    #TODO - raise an error here instead.

            elif isinstance(value, ObjectId):
                ret[key] = smart_str(value)

            elif isinstance(item, list):
                #list of things.
                dyn = DynamicField(**self.get_field_kwargs(self.model_field))
                ret[key] = [dyn.to_representation(i) for i in item]
            elif isinstance(item, numbers.Number) or isinstance(item, bool):
                #number/bool, just return the value.
                ret[key] = item
            else:
                #stringify
                ret[key] = smart_str(item)

        return ret

    def to_internal_value(self, data):
        return self.model_field.to_python(data)


class ObjectIdField(DocumentField):

    type_label = 'ObjectIdField'

    def get_fields(self):
        #return fields for all the subfields in this document.
        return {}

    def to_representation(self, value):
        return smart_str(value)

    def to_internal_value(self, data):
        return ObjectId(data)

class HyperlinkedDocumentIdentityField(HyperlinkedIdentityField):

    view_name_pattern = "%s-detail"

    def __init__(self, *args, **kwargs):
        pattern = kwargs.pop('view_name_pattern', None)
        if pattern:
            self.view_name_pattern = pattern

        if 'lookup_field' not in kwargs.keys():
            kwargs['lookup_field'] = 'id'

        cleanup = False
        if 'view_name' not in kwargs.keys():
            #fake out the parent class so it doesn't break.
            kwargs['view_name'] = ''
            cleanup = True

        super(HyperlinkedDocumentIdentityField, self).__init__(*args, **kwargs)

        if cleanup:
            self.view_name = None


    def to_representation(self, value):
        if self.view_name is None:
            self.view_name = self.view_name_pattern % value.__class__.__name__.lower()

        return super(HyperlinkedDocumentIdentityField, self).to_representation(value)

class FileField(DocumentField):
    """
    For now, just print the grid_id properly.
    Allowing uploads of files via the serializer will require a bit more work.
    """
    type_label = 'FileField'

    def to_representation(self, value):
        gid = value.grid_id

        return smart_str(value.grid_id)

class BinaryField(DocumentField):

    type_label = 'BinaryField'

    def __init__(self, **kwargs):
        try:
            self.max_bytes = kwargs.pop('max_bytes')
        except KeyError:
            raise ValueError('BinaryField requires "max_bytes" kwarg')
        super(BinaryField, self).__init__(**kwargs)

    def to_representation(self, value):
        return smart_str(value)

    def to_internal_value(self, data):
        return super(BinaryField, self).to_internal_value(smart_str(data))


class BaseGeoField(DocumentField):

    type_label = 'BaseGeoField'