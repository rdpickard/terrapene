# -*- coding: utf-8 -*-
__author__ = "Robert Daniel Pickard"
__date__ = "Dec 27, 2020"
__email__ = "code@chalkfarm.mx"
__function__ = ""

import os
import re
import logging
import json
import random
import string
import base64

import requests
import flask
import flask_restful
from flask_sqlalchemy import SQLAlchemy
import flask_sqlalchemy_session
import sqlalchemy
import sqlalchemy.orm
import flask_migrate

import jsonschema

application = flask.Flask(__name__)
application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
db = SQLAlchemy(application)
db_session_factory = sqlalchemy.orm.sessionmaker(bind=db.engine)
db_scoped_session = flask_sqlalchemy_session.flask_scoped_session(db_session_factory, application)
api = flask_restful.Api(application)

isbndb_webservice_api_key = os.environ["ISBNDB_WEBSERVICE_API_KEY"]

# Load the JSON schemas into objects for validating JSON objects later
with open("json_schemas/isbndb_dot_com_api_book_jsonschema.json") as f:
    isbndb_webservice_api_jsonschema_book = json.load(f)

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
    style = db.Column(db.String(120), unique=False, nullable=False, default="unknown")
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

    name = db.Column(db.String(256), unique=False, nullable=True)
    name_long = db.Column(db.String(1024), unique=False, nullable=True)

    logline = db.Column(db.String(1024), unique=False, nullable=True)

    isbn = db.Column(db.String(120), unique=False, nullable=True)
    isbn13 = db.Column(db.String(120), unique=False, nullable=True)
    isbn_unknown = db.Column(db.Boolean, unique=False, nullable=False, default=True)
    isbn_should_exist = db.Column(db.Boolean, unique=False, nullable=False, default=True)

    published_exact_day_utc = db.Column(db.DateTime(timezone=True), unique=False, nullable=True)
    published_estimated_range_start_day_utc = db.Column(db.DateTime(timezone=True), unique=False, nullable=True)
    published_estimated_range_end_day_utc = db.Column(db.DateTime(timezone=True), unique=False, nullable=True)

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


def gen_log_tag():
    """
    Generates a 8 character string of a mix of upper case letters and digits to be used in log messages
    :return: Eight character long string
    """
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))


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


def book_by_isbn_from_isbndb_dot_com(normalized_isbn, db_session, logger=logging.getLogger()):
    """
    Looks up a book or creates a new book by ISBN of a book edition and back fills the story and author
    :param normalized_isbn: The ISBN or ISBN13 of the book edition
    :param db_session: The sqlalchemy session to use to access local database
    :return: The database ID of the book edition. If no book with provided ISBN can be found return None
    :raises ValueError: If value normalized_isbn hasn't be normalized
    """

    log_tag = gen_log_tag()
    logger.debug("[log_tag:{}][isbn:{}] book_by_isbn_from_isbndb_dot_com called".format(log_tag, normalized_isbn))

    not_normalized_error_msg = "ISBN has not been normalized before passing to book_by_isbn function. Needs to be normalized first [log_tag:{}]".format(log_tag)
    try:
        if normalized_isbn != normalize_isbn(normalized_isbn):
            logger.info("[log_tag:{}][isbn:{}] Rejected isbn, wasn't normalized".format(log_tag, normalized_isbn))
            raise ValueError(not_normalized_error_msg)
    except ValueError:
        logger.info("[log_tag:{}][isbn:{}] Rejected isbn, wasn't well formatted".format(log_tag, normalized_isbn))
        raise ValueError(not_normalized_error_msg)

    # Look up the ISBN in the local database, if one is present return the local database id of the book edition

    book_edition = db.session.query(BookEdition).filter((BookEdition.isbn == normalized_isbn) | (BookEdition.isbn13 == normalized_isbn)).first()
    if book_edition is not None:
        logger.debug("[log_tag:{}][isbn:{}] in local db".format(log_tag, normalized_isbn))
        return book_edition.id
    logger.debug("[log_tag:{}][isbn:{}] NOT in local db".format(log_tag, normalized_isbn))

    # Look up the ISBN in the ISBN database service to get data to be used in local creation
    logger.debug("[log_tag:{}][isbn:{}] book_by_isbn_from_isbndb_dot_com api lookup request".format(log_tag, normalized_isbn))
    isbndb_response = requests.get("https://api2.isbndb.com/book/{}".format(normalized_isbn),
                                   headers={'Authorization': isbndb_webservice_api_key})
    logger.debug("[log_tag:{}][isbn:{}] book_by_isbn_from_isbndb_dot_com api lookup response {}".format(log_tag, normalized_isbn, isbndb_response.status_code))

    if isbndb_response.status_code == 404:
        logger.info("[log_tag:{}][isbn:{}] Web service isbndb.com api returned 404 for ISBN".format(log_tag, normalized_isbn))
        return None
    elif isbndb_response.status_code != 200:
        logger.warning("[log_tag:{}][isbn:{}] Web service isbndb.com api returned unhandled response code '{}' for ISBN".format(log_tag, normalized_isbn, isbndb_response.status_code))
        raise RemoteServiceException("Remote service isbndb responded with code {}. [log_tag:{}]".format(isbndb_response.status_code, log_tag))
    try:
        jsonschema.validate(isbndb_response.json(), isbndb_webservice_api_jsonschema_book)
    except jsonschema.exceptions.ValidationError as ve:
        logger.error("[log_tag:{}][isbn:{}] Validation of isbndb.com web service api return JSON of ISBN failed".format(log_tag, normalized_isbn))
        logger.error("[log_tag:{}][isbn:{}] validation failure msg(b64): {}".format(log_tag, normalized_isbn, base64.b64encode(str(ve).encode('ascii'))))
        logger.debug("[log_tag:{}][isbn:{}] validation failure msg: \n{}".format(log_tag, normalized_isbn, str(ve)))
        raise RemoteServiceException("Remote service isbndb api response did not send JSON in expected format. JSON schema validation failed [log_tag:{}]".format(log_tag))
    isbndb_book = isbndb_response.json()

    # Create a story edition of the story based on the book name
    story = Story(name=isbndb_book["book"]["title"])
    db_session.add(story)
    db_session.commit()

    story_edition = StoryEdition(story_id=story.id, story_edition_language=isbndb_book["book"]["language"])
    db_session.add(story_edition)
    db_session.commit()

    # Create a author for the story
    author_prosoponym_ids = list()
    for author in isbndb_book["book"]["authors"]:
        name = Prosoponym(name=author)
        person = Person()
        db_session.add(name)
        db_session.add(person)
        db_session.commit()

        name_to_person = NamesAssociation(prosoponym_id=name.id, person_id=person.id)
        db_session.add(name_to_person)
        db_session.commit()
        author_prosoponym_ids.append(name.id)

    # Associate the story with the author
    for author_prosoponym_id in author_prosoponym_ids:
        db_session.add(StoryEditionPersonAssociation(prosoponym_id=author_prosoponym_id,
                                                     story_edition_id=story_edition.id,
                                                     contribution="author"))
    db_session.commit()

    # Associate the story edition with the book edition
    book_edition = BookEdition(isbn13=isbndb_book["book"]["isbn13"], isbn=isbndb_book["book"]["isbn"])
    db_session.add(book_edition)
    db_session.commit()

    db_session.add(StoryEditionBookEditionAssociation(story_edition_id=story_edition.id,
                                                      book_edition_id=book_edition.id))

    return book_edition.id

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
    # if os.path.exists("/tmp/test.db"):
    #    os.remove("/tmp/test.db")
    db.create_all()

    application.debug = True

    try:
        book_id = book_by_isbn_from_isbndb_dot_com("0425192938", db.session, logger=application.logger)
    except RemoteServiceException as rse:
        application.logger.error(rse)
    print(book_id)
    application.run()
