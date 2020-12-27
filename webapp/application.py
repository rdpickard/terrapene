# -*- coding: utf-8 -*-
__author__ = "Robert Daniel Pickard"
__date__ = "Dec 27, 2020"
__email__ = "code@chalkfarm.mx"
__function__ = ""

import os
import re
import logging
from urllib.parse import urlparse
import time
import json
from datetime import datetime
import ipaddress

import requests
import flask
import flask_restful
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
import flask_migrate

application = flask.Flask(__name__)
application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
db = SQLAlchemy(application)
api = flask_restful.Api(application)
migrate = flask_migrate.Migrate(application, db)

isbndb_webservice_api_key = os.environ["ISBNDB_WEBSERVICE_API_KEY"]

# TODO the check of API key should be moved into flask pre-flight functions
if isbndb_webservice_api_key is None or len(isbndb_webservice_api_key) == 0:
    raise Exception("ISBNDB_WEBSERVICE_API_KEY not set")

class RemoteServiceException(Exception):
    pass

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    def __repr__(self):
        return '<User %r>' % self.username


class PhysicalStorage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(80), unique=True, nullable=False)
    human_readable_name = db.Column(db.String(120), unique=True, nullable=False)
    human_readable_description = db.Column(db.String(120), unique=True, nullable=False)
    human_readable_location = db.Column(db.String(120), unique=True, nullable=False)

    machine_readable_name = db.Column(db.String(120), unique=True, nullable=False)
    machine_readable_location = db.Column(db.String(120), unique=True, nullable=False)

    def __repr__(self):
        return '<PhysicalStorage %r>' % self.human_readable_name


"""
A general overview of the associations in the data base organize stories 

There is a base STORY
A STORY may have multiple versions that are differentiated into STORY_EDITIONS
Each STORY_EDITION is the creation of PERSONS who are contributors 
A STORY_EDITION could be appear in multiple BOOK_EDITIONS
a USER has COLLECTIONS that contain BOOK_EDITIONS
"""


class Story(db.Model):
    __tablename__ = 'story'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(2046), unique=False, nullable=False)

    based_on = db.Column(db.Integer, db.ForeignKey('story.id'))


class Prosoponym(db.Model):
    __tablename__ = 'prosoponym'
    id = db.Column(db.Integer, primary_key=True)
    is_pseudonym = db.Column(db.Boolean, unique=False, nullable=False, default=False)
    is_collective = db.Column(db.Boolean, unique=False, nullable=False, default=False)
    style = db.Column(db.String(120), unique=False, nullable=False)
    name = db.Column(db.String(2046), unique=False, nullable=False)


class Person(db.Model):
    __tablename__ = 'person'
    id = db.Column(db.Integer, primary_key=True)


class NamesAssociation(db.Model):
    __tablename__ = 'names_association'
    person_id = db.Column(db.Integer, db.ForeignKey('person.id'), primary_key=True)
    prosoponym_id = db.Column(db.Integer, db.ForeignKey('prosoponym.id'), primary_key=True)
    best_known_as = db.Column(db.Boolean, unique=False, nullable=False, default=False)
    widely_known_as = db.Column(db.Boolean, unique=False, nullable=False, default=False)

    association_confidence = db.Column(db.Integer)


class StoryEdition(db.Model):
    __tablename__ = 'story_edition'
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id'))

    edition_name = db.Column(db.String(120), unique=False, nullable=True)
    edition_identifier = db.Column(db.String(120), unique=False, nullable=True)

    story_edition_name = db.Column(db.String(120), unique=False, nullable=True)
    story_edition_language = db.Column(db.String(120), unique=False, nullable=True)
    story_edition_language_dialect = db.Column(db.String(2046), unique=False, nullable=True)


class StoryEditionPersonAssociation(db.Model):
    __tablename__ = 'story_edition_person_association'
    id = db.Column(db.Integer, primary_key=True)

    story_edition_id = db.Column(db.Integer, db.ForeignKey('story_edition.id'))
    prosoponym_id = db.Column(db.Integer, db.ForeignKey('prosoponym.id'))
    contribution = db.Column(db.String(120), unique=False, nullable=False)

    association_confidence = db.Column(db.Integer)


class BookEdition(db.Model):
    __tablename__ = 'book_edition'
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), unique=False, nullable=True)
    isbn = db.Column(db.String(120), unique=False, nullable=True)
    isbn13 = db.Column(db.String(120), unique=False, nullable=True)
    isbn_unknown = db.Column(db.Boolean, unique=False, nullable=False, default=True)
    isbn_should_exist = db.Column(db.Boolean, unique=False, nullable=False, default=True)

    physical = db.Column(db.Boolean, unique=False, nullable=False, default=True)

    human_readable_description = db.Column(db.String(120), unique=False, nullable=False, default="To be provided")


class StoryEditionBookEditionAssociation(db.Model):
    __tablename__ = 'story_edition_book_edition_association'
    id = db.Column(db.Integer, primary_key=True)

    story_edition_id = db.Column(db.Integer, db.ForeignKey('story_edition.id'))
    book_edition_id = db.Column(db.Integer, db.ForeignKey('person.id'))

    association_confidence = db.Column(db.Integer)


class UserCollection():
    __tablename__ = 'collection'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=False, nullable=False)


def normalize_isbn(isbn):
    """
    Strip out any separators between numbers as well as leading or trailing padding from an ISBN
    :param isbn: Input string that may contain separators or padding.
    :return: Normalized string of just digits
    :raises ValueError: If value can't be normalized to a well formed ISBN id
    """
    digits_only = re.sub("[^0-9]", "", isbn)
    if len(digits_only) == 10 or len(digits_only) == 13:
        return digits_only
    else:
        raise ValueError("ISBN string must be 10 or 13 digits long. Value '{}' has {}digits".format(digits_only, len(digits_only)))


def book_by_isbn(normalized_isbn, create_on_missing=True):
    """
    Looks up a book or creates a new book by ISBN of a book edition and back fills the story and author
    :param normalized_isbn: The ISBN or ISBN13 of the book edition
    :param create_on_missing: If the ISBN does not exist try to create an entry.
    :return: The database ID of the book edition. If ISBN does not exist in db and create_on_missing is False, return None
    :raises ValueError: If value normalized_isbn hasn't be normalized
    """

    if normalized_isbn != normalize_isbn(normalized_isbn):
        raise ValueError("ISBN has not been normalized before passing to book_by_isbn function. Needs to be normalized first")

    # Look up the ISBN in the local database,
    # -if none present and create_on_missing is False return None otherwise move on
    # -if one is present return the local database id of the book edition
    # -if none is present create_on_missing is True move on to createing a local entry
    book_edition = db.session.query(BookEdition).filter((BookEdition.isbn == normalized_isbn) | (BookEdition.isbn13 == normalized_isbn)).first()
    if book_edition is None and not create_on_missing:
        return None
    elif book_edition is not None:
        return book_edition.id

    # Look up the ISBN in the ISBN database service to get data to be used in local creation
    isbndb_response = requests.get("https://api2.isbndb.com/book/{}".format(normalized_isbn),
                                   headers={'Authorization': isbndb_webservice_api_key})

    if isbndb_response.status_code != 200:
        raise RemoteServiceException("isbndb responded with code {}".format(isbndb_response.status_code))

    print(isbndb_response.json())

    # Create a default story for the book based on the book name

    # Create a story edition of the story

    # Create a author for the story

    # Associate the story with the author

    # Associate the story edition with the book edition

    # Return the book edition for the ISBN

@application.before_first_request
def pre_first_request():

    # TODO need to check to see if the tables already exist
    db.create_all()


@application.route('/css/<path:path>')
def send_css(path):
    return flask.send_from_directory('staticfiles/css', path)


@application.route('/js/<path:path>')
def send_js(path):
    return flask.send_from_directory('staticfiles/js', path)


@application.route('/fonts/<path:path>')
def send_font(path):
    return flask.send_from_directory('staticfiles/fonts', path)


@application.route('/media/<path:path>')
def send_media(path):
    return flask.send_from_directory('staticfiles/media', path)


if __name__ == "__main__":
    os.remove("/tmp/test.db")
    db.create_all()

    """
    # Create a book
    name = Prosoponym(name="William Gibson", style="anglo")
    db.session.add(name)
    person = Person()
    db.session.add(person)
    db.session.commit()

    name_to_person = NamesAssociation(prosoponym_id=name.id, person_id=person.id)
    db.session.add(name_to_person)

    story = Story(name="Pattern Recognition")
    db.session.add(story)
    db.session.commit()

    story_edition_english = StoryEdition(story_id=story.id, story_edition_language="english")
    story_edition_french = StoryEdition(story_id=story.id, story_edition_language="french",
                                        story_edition_name="IDENTIFICATION DES SCHEMAS")
    db.session.add(story_edition_english)
    db.session.commit()

    db.session.add(story_edition_french)
    db.session.commit()

    english_author = StoryEditionPersonAssociation(prosoponym_id=name.id, story_edition_id=story_edition_english.id,
                                                   contribution="author")
    french_author = StoryEditionPersonAssociation(prosoponym_id=name.id, story_edition_id=story_edition_french.id,
                                                  contribution="author")
    db.session.add(english_author)
    db.session.add(french_author)
    db.session.commit()

    book_edition_english = BookEdition(isbn13="0425192938")
    book_edition_french = BookEdition(isbn13="9782846260725")
    db.session.add(book_edition_english)
    db.session.add(book_edition_french)
    db.session.commit()

    e1 = StoryEditionBookEditionAssociation(story_edition_id=story_edition_french.id,
                                            book_edition_id=book_edition_french.id)
    e2 = StoryEditionBookEditionAssociation(story_edition_id=story_edition_english.id,
                                            book_edition_id=book_edition_english.id)
    db.session.add(e1)
    db.session.add(e2)

    db.session.commit()
    """
    book_by_isbn("0425192938")

    application.run()
