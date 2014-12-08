from __future__ import unicode_literals
import warnings
from django.core.exceptions import ValidationError
from mongoengine.errors import ValidationError
from rest_framework import serializers
from rest_framework import fields
import mongoengine
from mongoengine.base import BaseDocument
from mongoengine.context_managers import no_dereference
from django.core.paginator import Page
from django.db import models
from django.forms import widgets
from django.utils.datastructures import SortedDict
from rest_framework.compat import get_concrete_model
from .fields import ReferenceField, ListField, EmbeddedDocumentField, DynamicField, MapField
from rest_framework.settings import api_settings
from rest_framework.relations import HyperlinkedRelatedField, HyperlinkedIdentityField, RelatedField
from bson import DBRef
from .ld import Namespaced
from rest_framework.reverse import reverse
from django.core.urlresolvers import resolve, get_script_prefix, NoReverseMatch
from mongoengine.errors import DoesNotExist
from django.core import validators

field_mapping = {
    mongoengine.FloatField: fields.FloatField,
    mongoengine.IntField: fields.IntegerField,
    mongoengine.DateTimeField: fields.DateTimeField,
    mongoengine.EmailField: fields.EmailField,
    mongoengine.URLField: fields.URLField,
    mongoengine.StringField: fields.CharField,
    mongoengine.BooleanField: fields.BooleanField,
    mongoengine.FileField: fields.FileField,
    mongoengine.ImageField: fields.ImageField,
    mongoengine.ObjectIdField: fields.Field,
    mongoengine.ReferenceField: ReferenceField,
    mongoengine.ListField: ListField,
    mongoengine.EmbeddedDocumentField: EmbeddedDocumentField,
    mongoengine.DynamicField: DynamicField,
    mongoengine.DecimalField: fields.DecimalField,
    mongoengine.MapField: MapField,
    mongoengine.DictField: DynamicField,
}

attribute_dict = {
    mongoengine.StringField: ['max_length'],
    mongoengine.DecimalField: ['min_value', 'max_value'],
    mongoengine.EmailField: ['max_length'],
    mongoengine.FileField: ['max_length'],
    mongoengine.ImageField: ['max_length'],
    mongoengine.URLField: ['max_length'],
}


class MongoEngineModelSerializerOptions(serializers.ModelSerializerOptions):
    """
    Meta class options for MongoEngineModelSerializer
    """
    def __init__(self, meta):
        super(MongoEngineModelSerializerOptions, self).__init__(meta)
        self.depth = getattr(meta, 'depth', 10)


class MongoEngineModelSerializer(serializers.ModelSerializer):
    """
    Model Serializer that supports Mongoengine
    """
    _options_class = MongoEngineModelSerializerOptions

    def perform_validation(self, attrs):
        """
        Rest Framework built-in validation + related model validations
        """
        for field_name, field in self.fields.items():
            if field_name in self._errors:
                continue

            source = field.source or field_name
            if self.partial and source not in attrs:
                continue

            if field_name in attrs and hasattr(field, 'model_field'):
                try:
                    attr = attrs[field_name]
                    if attr not in validators.EMPTY_VALUES:
                        field.model_field.validate(attr)
                except ValidationError as err:
                    self._errors[field_name] = str(err)

            try:
                validate_method = getattr(self, 'validate_%s' % field_name, None)
                if validate_method:
                    attrs = validate_method(attrs, source)
            except serializers.ValidationError as err:
                self._errors[field_name] = self._errors.get(field_name, []) + list(err.messages)

        if not self._errors:
            try:
                attrs = self.validate(attrs)
            except serializers.ValidationError as err:
                if hasattr(err, 'message_dict'):
                    for field_name, error_messages in err.message_dict.items():
                        self._errors[field_name] = self._errors.get(field_name, []) + list(error_messages)
                elif hasattr(err, 'messages'):
                    self._errors['non_field_errors'] = err.messages

        return attrs

    def restore_object(self, attrs, instance=None):
        if instance is not None:

            dynamic_fields = self.get_dynamic_fields(instance)
            all_fields = dict(dynamic_fields, **self.fields)
            # import ipdb; ipdb.set_trace()

            for key, val in attrs.items():
                field = all_fields.get(key)
                if not field or field.read_only:
                    continue

                key = getattr(field, 'source', None ) or key
                try:
                    setattr(instance, key, val)
                except ValueError:
                    self._errors[key] = self.error_messages['required']

        else:
            instance = self.opts.model(**attrs)
        return instance

    def get_default_fields(self):
        cls = self.opts.model
        opts = get_concrete_model(cls)
        fields = []
        fields += [getattr(opts, field) for field in cls._fields_ordered]

        ret = SortedDict()

        for model_field in fields:
            if isinstance(model_field, mongoengine.ObjectIdField):
                field = self.get_pk_field(model_field)
            else:
                field = self.get_field(model_field)

            if field:
                field.initialize(parent=self, field_name=model_field.name)
                ret[model_field.name] = field

        for field_name in self.opts.read_only_fields:
            assert field_name in ret,\
            "read_only_fields on '%s' included invalid item '%s'" %\
            (self.__class__.__name__, field_name)
            ret[field_name].read_only = True

        return ret

    def get_dynamic_fields(self, obj):
        dynamic_fields = {}
        if obj is not None and obj._dynamic:
            for key, value in obj._dynamic_fields.items():
                dynamic_fields[key] = self.get_field(value)
        return dynamic_fields

    def get_field(self, model_field):
        kwargs = {}

        if model_field.__class__ in (mongoengine.ReferenceField, mongoengine.EmbeddedDocumentField,
                                     mongoengine.ListField, mongoengine.DynamicField,
                                     mongoengine.DictField, mongoengine.MapField):
            kwargs['model_field'] = model_field
            kwargs['depth'] = self.opts.depth

        if not model_field.__class__ == mongoengine.ObjectIdField:
            kwargs['required'] = model_field.required

        if model_field.__class__ == mongoengine.EmbeddedDocumentField:
            kwargs['document_type'] = model_field.document_type

        if model_field.default:
            kwargs['required'] = False
            kwargs['default'] = model_field.default

        if model_field.__class__ == models.TextField:
            kwargs['widget'] = widgets.Textarea

        if model_field.__class__ in attribute_dict:
            attributes = attribute_dict[model_field.__class__]
            for attribute in attributes:
                kwargs.update({attribute: getattr(model_field, attribute)})

        try:
            return field_mapping[model_field.__class__](**kwargs)
        except KeyError:
            # Defaults to WritableField if not in field mapping
            return fields.WritableField(**kwargs)

    def to_native(self, obj):
        """
        Rest framework built-in to_native + transform_object
        """
        ret = self._dict_class()
        ret.fields = self._dict_class()

        #Dynamic Document Support
        dynamic_fields = self.get_dynamic_fields(obj)
        all_fields = self._dict_class()
        all_fields.update(self.fields)
        all_fields.update(dynamic_fields)
        with Namespaced(lookup_uri(self)):
            for field_name, field in all_fields.items():
                if field.read_only and obj is None:
                    continue
                field.initialize(parent=self, field_name=field_name)
                key = self.get_field_key(field_name)
                value = field.field_to_native(obj, field_name)
                #Override value with transform_ methods
                method = getattr(self, 'transform_%s' % field_name, None)
                if callable(method):
                    value = method(obj, value)
                if not getattr(field, 'write_only', False):
                    ret[key] = value
                ret.fields[key] = self.augment_field(field, field_name, key, value)

        return ret

    def from_native(self, data, files=None):
        self._errors = {}

        if data is not None or files is not None:
            attrs = self.restore_fields(data, files)
            for key in data.keys():
                if key not in attrs:
                    attrs[key] = data[key]
            if attrs is not None:
                attrs = self.perform_validation(attrs)
        else:
            self._errors['non_field_errors'] = ['No input provided']

        if not self._errors:
            return self.restore_object(attrs, instance=getattr(self, 'object', None))

    @property
    def data(self):
        """
        Returns the serialized data on the serializer.
        """
        if self._data is None:
            obj = self.object

            if self.many is not None:
                many = self.many
            else:
                many = hasattr(obj, '__iter__') and not isinstance(obj, (BaseDocument, Page, dict))
                if many:
                    warnings.warn('Implicit list/queryset serialization is deprecated. '
                                  'Use the `many=True` flag when instantiating the serializer.',
                                  DeprecationWarning, stacklevel=2)

            if many:
                self._data = [self.to_native(item) for item in obj]
            else:
                self._data = self.to_native(obj)

        return self._data


class HyperlinkedModelSerializerOptions(MongoEngineModelSerializerOptions):
    """
    Options for HyperlinkedModelSerializer
    """
    def __init__(self, meta):
        super(HyperlinkedModelSerializerOptions, self).__init__(meta)
        self.view_name = getattr(meta, 'view_name', None)
        self.lookup_field = getattr(meta, 'lookup_field', None)
        self.url_field_name = getattr(meta, 'url_field_name', api_settings.URL_FIELD_NAME)  # todo change back to id for json-ld


class MongoEngineHyperlinkedIdentityField(HyperlinkedIdentityField):
    lookup_field = 'id'


class MongoHyperlinkedRelatedField(HyperlinkedRelatedField):
    lookup_field = 'id'
    def initialize(self, parent, field_name):
        super(RelatedField, self).initialize(parent, field_name)
        if self.queryset is None and not self.read_only:
            manager = getattr(self.parent.opts.model, self.source or field_name)
            self.queryset = manager.document_type.objects.all()


class HyperlinkedModelSerializer(MongoEngineModelSerializer):
    """
    A subclass of ModelSerializer that uses hyperlinked relationships,
    instead of primary key relationships.
    """
    _options_class = HyperlinkedModelSerializerOptions
    _default_view_name = '%(model_name)s-detail'
    _hyperlink_field_class = MongoHyperlinkedRelatedField
    _hyperlink_identify_field_class = MongoEngineHyperlinkedIdentityField

    def get_default_fields(self):
        fields = super(HyperlinkedModelSerializer, self).get_default_fields()

        if self.opts.view_name is None:
            self.opts.view_name = self._get_default_view_name(self.opts.model)

        if self.opts.url_field_name not in fields:
            url_field = self._hyperlink_identify_field_class(
                view_name=self.opts.view_name,
                lookup_field=self.opts.lookup_field
            )
            ret = self._dict_class()
            ret[self.opts.url_field_name] = url_field
            ret.update(fields)
            fields = ret

        return fields

    def get_pk_field(self, model_field):
        if self.opts.fields and model_field.name in self.opts.fields:
            return self.get_field(model_field)

    def get_related_field(self, model_field, related_model, to_many):
        """
        Creates a default instance of a flat relational field.
        """
        # TODO: filter queryset using:
        # .using(db).complex_filter(self.rel.limit_choices_to)
        kwargs = {
            'queryset': related_model._default_manager,
            'view_name': self._get_default_view_name(related_model),
            'many': to_many
        }

        if model_field:
            kwargs['required'] = not(model_field.null or model_field.blank)
            if model_field.help_text is not None:
                kwargs['help_text'] = model_field.help_text
            if model_field.verbose_name is not None:
                kwargs['label'] = model_field.verbose_name

        if self.opts.lookup_field:
            kwargs['lookup_field'] = self.opts.lookup_field

        return self._hyperlink_field_class(**kwargs)

    def get_identity(self, data):
        """
        This hook is required for bulk update.
        We need to override the default, to use the url as the identity.
        """
        try:
            return data.get(self.opts.url_field_name, None)
        except AttributeError:
            return None

    def _get_default_view_name(self, model):
        """
        Return the view name to use if 'view_name' is not specified in 'Meta'
        """
        model_meta = model._meta
        format_kwargs = {
            'app_label': model_meta['collection'],
            'model_name': model_meta['collection'].lower()
        }
        return self._default_view_name % format_kwargs

    @property
    def data(self):
        """
        Returns the serialized data on the serializer.
        """
        if self._data is None:
            if hasattr(self.object, 'no_dereference'):
                obj = self.object.no_dereference()
            else:
                obj = self.object

            if self.many is not None:
                many = self.many
            else:
                many = hasattr(obj, '__iter__') and not isinstance(obj, (BaseDocument, Page, dict))
                if many:
                    warnings.warn('Implicit list/queryset serialization is deprecated. '
                                  'Use the `many=True` flag when instantiating the serializer.',
                                  DeprecationWarning, stacklevel=2)

            if many:
                self._data = [self.to_native(item) for item in obj]
            else:
                self._data = self.to_native(obj)

        return self._data


def lookup_uri(self):
    view = self.context.get('view', None)
    lookup_field = view.lookup_field if view else 'id'
    request = self.context.get('request', None)
    format = self.context.get('format', None)

    def uri(cls, id):
        try:
            kwargs = {lookup_field: str(id)}
            view_name = self._default_view_name % {'model_name': cls.lower()}
            return reverse(view_name, kwargs=kwargs, request=request, format=format)
        except NoReverseMatch:
            return '{1}'.format(cls, id)
    return uri