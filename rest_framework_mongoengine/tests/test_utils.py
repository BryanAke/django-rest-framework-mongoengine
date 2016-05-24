__author__ = 'BryanAke@gmail.com'

from unittest import TestCase
from rest_framework_mongoengine.utils import PolymorphicChainMap
from rest_framework_mongoengine.serializers import PolymorphicDocumentSerializer
from test_models import Vehicle, Car, Truck, Mileage, FuelMileage

##tests for PolymorphicChainMap
class DummySerializer(PolymorphicDocumentSerializer):
    class Meta:
        model = Vehicle


class TestPolymorphicChainMap(TestCase):

    def test_uses_serializer_fields(self):
        chainmap = PolymorphicChainMap()
        assert False

    def test_works_with_no_subclasses(self):
        assert False

    def test_subclass_uses_parents_fields(self):
        assert False

    def test_subclass_overwrites_parent_fields(self):
        assert False

    def test_subclass_adds_own_fields(self):
        assert False

    def test_grandchild_class_chains_correctly(self):
        assert False

    def test_siblings_dont_interfere(self):
        assert False