
#
# A simple blogging platform based on
# https://charlesleifer.com/blog/how-to-make-a-flask-blog-in-one-hour-or-less/
#


##################
# Imports
##################

import datetime
import functools
import os
import re
import urllib

from flask import (Flask, abort, flash, Markup, redirect, render_template,
                   request, Response, session, url_for)

# used for rendering the article body
from markdown import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.extra import ExtraExtension

# micawber supplies a few methods for retrieving rich metadata about a variety of links, such as links to youtube videos
from micawber import bootstrap_basic, parse_html
from micawber.cache import Cache as OEmbedCache

# peewee and the playhoouse extensions deal with database management
from peewee import *
from playhouse.flask_utils import FlaskDB, get_object_or_404, object_list
from playhouse.sqlite_ext import *


##################
# Configs
##################

# TODO: change to a one-way hash
ADMIN_PASSWORD = 'secret'

# os.path.realpath - Return the canonical path of the specified filename, eliminating any symbolic links encountered in the path
# __file__ - prints out the file location
APP_DIR = os.path.dirname(os.path.realpath(__file__))

DATABASE = 'sqliteext:///%s' % os.path.join(APP_DIR, 'blog.db')

DEBUG = False

# used by flask to encrypt the session cookie
# TODO: Do I need to change this in the future?
SECRET_KEY = "secret"

SITE_WIDTH = 800

app = Flask(__name__)

# my best guess is that this is importing the config variables from this
# file in particular, so you can declare them cleanly as above without calling
# a bunch of specific methods
app.config.from_object(__name__)

# from http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#flask-utils
# The FlaskDB class is a wrapper for configuring and referencing a Peewee database from within a Flask application.
# Don’t let its name fool you: it is not the same thing as a peewee database.
# FlaskDB is designed to remove the following boilerplate from your flask app:
#    Dynamically create a Peewee database instance based on app config data.
#    Create a base class from which all your application’s models will descend.
#    Register hooks at the start and end of a request to handle opening and closing a database connection.
flask_db = FlaskDB(app)
database = flask_db.database

# as far as I can tell this loads provider information into micawber for converting
# to convert urls into embeddable content, I think micawber.Cache has basic stored
# info about these providers?
oembed_providers = bootstrap_basic(OEmbedCache())


##################
# Databse Classes
##################

# creates a model class for the entry table
class Entry(flask_db.Model):

    # Field class for storing strings
    title = CharField()

    # from https://www.sqlitetutorial.net/sqlite-unique-constraint/
    # A UNIQUE constraint ensures all values in a column or a group of columns
    # are distinct from one another or unique.
    # we're using this to create a URL-friendly version of the title
    slug = CharField(unique=True)

    # Field class for storing text.
    content = TextField()

    # from https://www.sqlitetutorial.net/sqlite-index/
    # The index contains data from the columns that you specify in the index
    # and the corresponding rowid value. This helps SQLite quickly locate the
    # row based on the values of the indexed columns.
    # we will use this to determine if the articles should be displayed on the
    # site or not
    published = BooleanField(index=True)
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)

    def save(self, *args, **kwargs):
        # replace the non-URL-friendly characters and put that in self.slug
        if not self.slug:
            # \w     - matches any word character (alphanumeric & underscore)
            # [^\w]  - matches anything not in the set
            # [^\w]+ - matches one or more of the preceding
            self.slug = re.sub('[^\w]+', '-', self.title.lower())

        # this explicity puts the super() arguments Entry, self when you can
        # just say super()
        # saves the Entry instance into the database
        ret = super(Entry, self).save(*args, **kwargs)

        # store search content
        self.update_search_index()

        # returns number of rows modified
        return ret

    # updates the FTSEntry table used for fast searching of all articles
    def update_search_index(self):

        search_content = '\n'.join((self.title, self.content))

        # check to see if there's already an FTSEntry for this article
        try:
            # previously this had docid instead of rowid, but this (http://docs.peewee-orm.com/en/latest/peewee/sqlite_ext.html#FTSModel)
            # there is an automatically created rowid
            fts_entry = FTSEntry.get(FTSEntry.rowid == self.id)

        # if there's not one, create it
        except FTSEntry.DoesNotExist:
            # previously this had docid instead of rowid, but this (http://docs.peewee-orm.com/en/latest/peewee/sqlite_ext.html#FTSModel)
            # there is an automatically created rowid
            FTSEntry.create(rowid = self.id, content=search_content)

        # if there is one, update the contents and save
        else:
            fts_entry.content = search_content
            fts_entry.save()

    # Class methods are like instance methods, except that instead of the instance
    # of an object being passed as the first positional self argument, the class
    # itself is passed as the first argument.
    # from https://www.geeksforgeeks.org/classmethod-in-python/:
    # - A class method is a method which is bound to the class and not the object of the class.
    # - They have the access to the state of the class as it takes a class parameter
    # that points to the class and not the object instance.
    # - It can modify a class state that would apply across all the instances of the
    # class. For example, it can modify a class variable that would be applicable
    # to all the instances.
    @classmethod
    def public(cls):
        return Entry.select().where(Entry.published == True)

# FTS stands for Full Text Search, which is an extension of SQLite's virtual
# table functionality
# from https://sqlite.org/vtab.html
# virtual tables - registered with an open database connection, a virtual table
# object looks like a table, but does not actually read or write to the database
# file, instead it could represent in-memory data structures or data on disk that
# is not in the SQLite database format
class FTSEntry(FTSModel):

    # only for use in full-text search virtual tables
    content = SearchField()

    # some kind of strange thing peewee does to relate a database to the
    # class without using the above method in the class inheritance field
    class Meta:
        database = database


##################
# Application Functions
##################

# custom wrapper to redirect user to login page if they're trying to
# access an admin-only page
def login_required(fn):

    # basically a wrapper that alters metadata to show the original function
    # and not, in this case, the inner function, and also passes arguments
    # from the original fn to the new function inner
    @functools.wraps(fn)
    def inner(*args, **kwargs):

        # session is a flask object that behaves like a dict, but is really a
        # signed cookie, and can be used to store information between requests
        # 'logged_in' is a keyword with a possible True response
        if session.get('logged_in'):
            return fn(*args, **kwargs)

        # redirect returns a Response object that redirects the client to the
        # target location
        # url_for generates a url for the given endpoint, next is retrieved
        # by the login method
        # request.path -- the requested path as unicode
        return redirect(url_for('login', next=request.path))

    return inner

# i have no idea what this function does yet and can't seem to figure it out
# the only instance I have seen this used is in templates/includes/pagination.html
@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
    querystring = dict((key, value) for key, value in request_args.items())
    for key in keys_to_remove:
        querystring.pop(key, None)
    querystring.update(new_values)

    # previously this had urllib.urlencode but it is now at the below
    return urllib.parse.urlencode(querystring)

# errorhandler - Register a function to handle errors by code or exception class.
@app.errorhandler(404)
def not_found(exc):
    return Response('<h3>Not Found</h3>'), 404


##################
# Routes
##################

@app.route('/login/', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next') or request.form.get('next')

    # if the user is submitting the password for authentication
    if request.method == 'POST' and request.form.get('password'):
        # TODO: implement hashing algorithm
        password = request.form.get('password')
        if password == app.config['password']:
            # set the value in the cookie
            session['logged_in'] == True
            # store the cookie for more than this session
            session.permanent = True

            # flashes a message to the next request that can only be
            # retrieved by get_flashed_messages()
            flash('You are now logged in.', 'success')
            return redirect(next_url or url_for('index'))
        else:
            flash('Incorrect password.', 'danger')

    # template has action="{{ url_for('login', next=next_url) }}" in
    # the form for entering the password
    return render_template('login.html', next_url=next_url)

@app.route('/logout/', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        # clear the cookie
        session.clear()
        return redirect(url_for('login'))
    return render_template('logout.html')

##################
# App Initialization
##################

def main():
    # create tables if they don't already exist
    database.create_tables([Entry, FTSEntry])
    app.run(debug=True)

# hooo
if __name__ == '__main__':
    main()
