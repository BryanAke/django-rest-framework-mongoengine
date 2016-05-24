from datetime import datetime 
import mongoengine as me 
from unittest import TestCase
from bson import objectid

from django.conf import settings

from rest_framework import fields as drf_fields

from rest_framework_mongoengine.serializers import DocumentSerializer, PolymorphicDocumentSerializer
from test_models import Vehicle, Car, Truck, Mileage, FuelMileage

class VehicleSerializer(DocumentSerializer):

    class Meta:
        model = Vehicle

class TestDocumentSerializer(TestCase):

    def test_serializes_object(self):
        data = {
            'id': None,
            'name': 'DMC 12',
            'manufacturer': 'Delorean Motor Company',
            'weight': 4000
        }
        vehicle = Vehicle(name='DMC 12', manufacturer='Delorean Motor Company', weight=4000)

        serializer = VehicleSerializer(instance=vehicle)
        d = serializer.data
        self.assertDictEqual(d, data)

    def test_create_object(self):
        data = {
            'id': None,
            'name': 'DMC 12',
            'manufacturer': 'Delorean Motor Company',
            'weight': 4000
        }
        vehicle = Vehicle(name='DMC 12', manufacturer='Delorean Motor Company', weight=4000)

        serializer = VehicleSerializer()
        i = serializer.create(data)
        self.assertEqual(i.name, vehicle.name)
        self.assertEqual(i.weight, vehicle.weight)
        self.assertEqual(i.manufacturer, vehicle.manufacturer)

        i.delete()

    def test_fields_population(self):
        serializer = VehicleSerializer()
        f = serializer.fields

        #should be 4 fields when populated from model
        self.assertTrue(len(f) == 4)

        self.assertListEqual(f.keys(), ['id', 'name', 'weight', 'manufacturer'])

        self.assertTrue(isinstance(f['weight'], drf_fields.IntegerField))
        self.assertTrue(isinstance(f['name'], drf_fields.CharField))
        self.assertTrue(isinstance(f['weight'], drf_fields.IntegerField))