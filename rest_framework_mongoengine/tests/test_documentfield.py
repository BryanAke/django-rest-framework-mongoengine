__author__ = 'bake3'
from rest_framework_mongoengine.fields import DocumentField

import mongoengine as me
from unittest import TestCase

class TestDocumentSerializer(TestCase):
    def setUp(self):
        self.data = {
            'name': 'some anme',
            'location': {
                'city': 'Toronto'
            },
            'categories': [{'id': 'cat1'}, {'id': 'category_2', 'counter': 666}],
            'codes': [{'key': 'mykey1'}]
        }

    def test_lazy_fields(self):
        #fields attribute shouldn't populate until needed
        self.assertTrue(False)

    def test_fields_from_serializer(self):
        #serializer field mapping should be passed up to the serializer.
        self.assertTrue(False)

    def test_get_attribute(self):
        #get_attribute step should get the relevant attributes from the model
        self.assertTrue(False)

    def test_to_representation(self):
        #to_representation gets the attributes from get_attribute and turns them into the
        #serialized representation of the attribute.
        self.assertTrue(False)

    def test_