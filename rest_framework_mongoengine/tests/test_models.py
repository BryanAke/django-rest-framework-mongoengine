__author__ = 'BryanAke@gmail.com'

from mongoengine.document import Document, EmbeddedDocument
from mongoengine import fields

class Manufacturer(Document):
    name = fields.StringField()

class Vehicle(Document):
    name = fields.StringField()
    weight = fields.IntField()

    meta = {
        'allow_inheritance': True
    }

    manufacturer = fields.StringField()

class Car(Vehicle):
    manufacturer = fields.ReferenceField(Manufacturer)
    mpg = fields.IntField()


class Mileage(EmbeddedDocument):
    loaded = fields.IntField()
    unloaded = fields.IntField()

    meta = {
        'allow_inheritance': True
    }

class FuelMileage(Mileage):
    e85 = fields.IntField()
    unleaded = fields.IntField()


class Truck(Vehicle):
    mpg = fields.EmbeddedDocumentField(Mileage)

