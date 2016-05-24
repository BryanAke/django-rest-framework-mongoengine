from collections import namedtuple
from django.core.exceptions import ImproperlyConfigured
from django.utils import six

import collections
from rest_framework.utils.serializer_helpers import BindingDict

from mongoengine.base.common import get_document
import mongoengine

from collections import OrderedDict
from rest_framework.utils import field_mapping
import inspect


FieldInfo = namedtuple('FieldResult', [
    'pk',  # Model field instance
    'fields',  # Dict of field name -> model field instance
    'forward_relations',  # Dict of field name -> RelationInfo
    'reverse_relations',  # Dict of field name -> RelationInfo
    'fields_and_pk',  # Shortcut for 'pk' + 'fields'
    'relations'  # Shortcut for 'forward_relations' + 'reverse_relations'
])

RelationInfo = namedtuple('RelationInfo', [
    'model_field',
    'related',
    'to_many',
    'has_through_model'
])


def _resolve_model(obj):
    """
    Inherited from rest_framework.utils.model_meta
    Overridden for MongoDB compability
    """
    if isinstance(obj, six.string_types) and len(obj.split('.')) == 2:
        app_name, model_name = obj.split('.')
        resolved_model = get_document(model_name)
        if resolved_model is None:
            msg = "Mongoengine did not return a model for {0}.{1}"
            raise ImproperlyConfigured(msg.format(app_name, model_name))
        return resolved_model
    elif inspect.isclass(obj) and issubclass(obj, mongoengine.BaseDocument):
        return obj
    raise ValueError("{0} is not a MongoDB Document".format(obj))


def get_field_info(model):
    """
    Given a model class, returns a `FieldInfo` instance containing metadata
    about the various field types on the model.
    """
    # Deal with the primary key.
    pk = model.id if not issubclass(model, mongoengine.EmbeddedDocument) else None

    # Deal with regular fields.
    fields = OrderedDict()

    for field_name in model._fields_ordered:
        fields[field_name] = model._fields[field_name]

    # Deal with forward relationships.
    # Pass forward relations since there is no relations on mongodb
    forward_relations = OrderedDict()

    # Deal with reverse relationships.
    # Pass reverse relations since there is no relations on mongodb
    reverse_relations = OrderedDict()

    # Shortcut that merges both regular fields and the pk,
    # for simplifying regular field lookup.
    fields_and_pk = OrderedDict()
    fields_and_pk['pk'] = pk
    fields_and_pk[getattr(pk, 'name', 'pk')] = pk
    fields_and_pk.update(fields)

    # Shortcut that merges both forward and reverse relationships

    relations = OrderedDict(
        list(forward_relations.items()) +
        list(reverse_relations.items())
    )

    return FieldInfo(pk, fields, forward_relations, reverse_relations, fields_and_pk, relations)

class PolymorphicChainMap(object):
    #that's a mouthful.
    #more like a TreeChainMap or something?

    lookup = {}

    def __init__(self, serializer, base_fields=None, klazz=None):
        #pass in base class kls that will be the root type for a serializer.
        if klazz is not None:
            self.klass = klazz
        else:
            self.klass = serializer.Meta.model
        self.serializer = serializer
        if base_fields:
            self.base_dict = base_fields
            self.lookup[self.klass] = ChainMap(self.base_dict)
        #else:
        #    self.base_dict = BindingDict(serializer)
        #    for key, field in self.klass._fields.items():
        #        self.base_dict[key] = serializer.get_field_mapping(field)(**serializer.get_field_kwargs(field))

    def __getitem__(self, item):
        if not isinstance(item, type):
            item = item.__class__

        #if we haven't initialized the base_dict, use the serializer's field property.
        if not hasattr(self, 'base_dict'):
            self.base_dict = self.serializer.fields
            self.lookup[self.klass] = ChainMap(self.base_dict)

        #see if we've generated this chainmap yet.
        if item in self.lookup:
            return self.lookup[item]

        #check if we can generate it, then generate it.
        if not issubclass(item, self.klass):
            raise AssertionError("Can only serialize objects that inherit from the base model.")

        last_kls = self.klass

        for kls in inspect.getmro(item)[::-1]:
            if issubclass(self.klass, kls):
                continue
            if kls in self.lookup:
                last_kls = kls
                continue
            #{key: value for key, value in instance.__class__._fields.items() if value not in self.Meta.model._fields.values()}
            delta = {key: field for key, field in kls._fields.items() if field not in last_kls._fields.values()}

            #construct the next tier of the chainmap
            delta_fields = BindingDict(self.serializer)
            for key, field in delta.items():
                delta_fields[key] = self.serializer.get_field_mapping(field)(**self.serializer.get_field_kwargs(field))

            self.lookup[kls] = ChainMap(delta_fields, self.lookup[last_kls])
        return self.lookup[kls]





class ChainMap(collections.MutableMapping):
    """A ChainMap groups multiple dicts (or other mappings) together
    to create a single, updateable view.

    The underlying mappings are stored in a list.  That list is public and can
    be accessed or updated using the *maps* attribute.  There is no other state.

    Lookups search the underlying mappings successively until a key is found.
    In contrast, writes, updates, and deletions only operate on the first
    mapping.
    """

    def __init__(self, *maps):
        """Initialize a ChainMap by setting *maps* to the given mappings.
        If no mappings are provided, a single empty dictionary is used.
        """
        self._maps = list(maps) or [{}]  # always at least one map

    def __missing__(self, key):
        raise KeyError(key)

    def __lookup(self, key):
        for mapping in self._maps:
            try:
                return mapping[key]  # can't use 'key in mapping' with defaultdict
            except KeyError:
                pass
        return self.__missing__(key)  # support subclasses that define __missing__

    def __getitem__(self, key):
        value = self.__lookup(key)
        if value is None and len(self.parents) > 0:
            try:
                value = self.parents[key]
            except KeyError:
                pass
        return value

    def get(self, key, default=None):
        return self[key] if key in self else default

    def __len__(self):
        return len(set().union(*self._maps))  # reuses stored hash values if possible

    def __iter__(self):
        return iter(set().union(*self._maps))

    def __contains__(self, key):
        return any(key in m for m in self._maps)

    def __bool__(self):
        return any(self._maps)

    def __repr__(self):
        return '{0.__class__.__name__}({1})'.format(
            self, ', '.join(map(repr, self._maps)))

    @classmethod
    def fromkeys(cls, iterable, *args):
        'Create a ChainMap with a single dict created from the iterable.'
        return cls(dict.fromkeys(iterable, *args))

    def copy(self):
        'New ChainMap or subclass with a new copy of maps[0] and refs to maps[1:]'
        return self.__class__(self._maps[0].copy(), *self._maps[1:])

    __copy__ = copy

    def new_child(self, m=None):  # like Django's Context.push()
        """
        New ChainMap with a new map followed by all previous maps. If no
        map is provided, an empty dict is used.
        """
        if m is None:
            m = {}
        return self.__class__(m, *self._maps)

    @property
    def parents(self):  # like Django's Context.pop()
        """New ChainMap from maps[1:]."""
        return self.__class__(*self._maps[1:])

    def __setitem__(self, key, value):
        self._maps[0][key] = value

    def __delitem__(self, key):
        try:
            del self._maps[0][key]
        except KeyError:
            raise KeyError('Key not found in the first mapping: {!r}'.format(key))

    def popitem(self):
        """Remove and return an item pair from maps[0]. Raise KeyError if maps[0] is empty."""
        try:
            return self._maps[0].popitem()
        except KeyError:
            raise KeyError('No keys found in the first mapping.')

    def pop(self, key, *args):
        """Remove *key* from maps[0] and return its value. Raise KeyError if *key* not in maps[0]."""
        try:
            return self._maps[0].pop(key, *args)
        except KeyError:
            raise KeyError('Key not found in the first mapping: {!r}'.format(key))

    def clear(self):
        """Clear maps[0], leaving maps[1:] intact."""
        self._maps[0].clear()