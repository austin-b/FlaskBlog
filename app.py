
#
# A simple blogging platform based on
# https://charlesleifer.com/blog/how-to-make-a-flask-blog-in-one-hour-or-less/
#
# TODO: add tags to search functionality
# TODO: add tags to index page
# TODO: in detail view, make tags link to a search
# TODO: add about me page



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

# REVIEW: change if not utilizing https
ADMIN_PASSWORD = 'secret'

# os.path.realpath - Return the canonical path of the specified filename, eliminating any symbolic links encountered in the path
# __file__ - prints out the file location
APP_DIR = os.path.dirname(os.path.realpath(__file__))

DATABASE = 'sqliteext:///%s' % os.path.join(APP_DIR, 'blog.db')

DEBUG = False

# used by flask to encrypt the session cookie
# random value obtained from os.urandom
SECRET_KEY = b'&iRy\xed{\x1aD\xb8\xef\xbc8\x02\n\xf3\x02"6\xc8~\x82o[\xc9'

SITE_WIDTH = 800

# user agent used by blog_entry_uploader.py
UPLOADER_USER_AGENT = 'tommy/post-uploader'

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

# TODO: create and display tags for each entry
# creates a model class for the entry table
class Entry(flask_db.Model):

    # Field class for storing strings
    title = CharField()

    # from https://www.sqlitetutorial.net/sqlite-unique-constraint/
    # A UNIQUE constraint ensures all values in a column or a group of columns
    # are distinct from one another or unique.
    # we're using this to create a URL-friendly version of the title
    slug = CharField(unique=True)

    summary = CharField()

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

    @property
    def html_content(self):

        # used for code/syntax highlighting
        # css_class -- name of css class used for div
        hilite = CodeHiliteExtension(linenums=True, css_class='highlight')

        # all the extensions found here:
        # https://python-markdown.github.io/extensions/extra/
        extras = ExtraExtension()

        # utilizes the above extensions and converts the markdown to html
        markdown_content = markdown(self.content, extensions=[hilite, extras])

        # parse_html -- Parse HTML intelligently, rendering items on their own
        # within block elements as full content (e.g. a video player)
        # urlize_all -- constructs a simple link when provider is not found
        oembed_content = parse_html(
            markdown_content,
            oembed_providers,
            urlize_all=True,
            maxwidth=app.config['SITE_WIDTH'])

        # Markup returns a string that is ready to be safely inserted into
        # an HTML document
        return Markup(oembed_content)

    def save(self, *args, **kwargs):
        # replace the non-URL-friendly characters and put that in self.slug
        if not self.slug:
            # \w     - matches any word character (alphanumeric & underscore)
            # [^\w]  - matches anything not in the set
            # [^\w]+ - matches one or more of the preceding
            self.slug = re.sub('[^\w]+', '-', self.title.lower())

        self.update_summary()

        # this explicity puts the super() arguments Entry, self when you can
        # just say super()
        # saves the Entry instance into the database
        ret = super(Entry, self).save(*args, **kwargs)

        # store search content
        self.update_search_index()

        # returns number of rows modified
        return ret

    def add_tags(self, *args):
        new_tag_count = 0
        new_entrytag_count = 0
        for t in args:
            # returns a tuple of model instance and boolean showing whether or
            # not the entry was created
            (tag, tag_created) = Tag.get_or_create(title = t)

            if tag_created:
                new_tag_count += 1

            (_, entrytag_created) = EntryTag.get_or_create(entry = self, tag = tag)

            if entrytag_created:
                new_entrytag_count += 1

        # returning for basic debug
        return (new_tag_count, new_entrytag_count)

    def get_tags(self):
        return [tag.tag.title for tag in self.tags]

    # creates a basic 100 character summary
    def update_summary(self):
        matches = re.findall('[A-Za-z\s\,\.]+[^<*>]\w+', self.content[:200])
        print(matches)
        match = " ".join(matches)
        self.summary = match[:100]

    # updates the FTSEntry table used for fast searching of all articles
    def update_search_index(self):

        search_content = '\n'.join((self.title, self.content))

        # check to see if there's already an FTSEntry for this article
        try:
            fts_entry = FTSEntry.get(FTSEntry.docid == self.id)

        # if there's not one, create it
        except FTSEntry.DoesNotExist:
            # previously this had docid instead of rowid, but this (http://docs.peewee-orm.com/en/latest/peewee/sqlite_ext.html#FTSModel)
            # there is an automatically created rowid
            FTSEntry.create(rowid = self.id, content=search_content)

        # if there is one, update the contents and save
        else:
            fts_entry.content = search_content
            fts_entry.save()

    # wrapper for super delete_instance
    def delete_instance(self, *args, **kwargs):

        ret = super(Entry, self).delete_instance(*args, **kwargs)

        self.delete_search_index()

        return ret

    def delete_search_index(self):

        fts_entry = FTSEntry.get(FTSEntry.docid == self.id)

        fts_entry.delete_instance()

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

    @classmethod
    def drafts(cls):
        return Entry.select().where(Entry.published == False)

    @classmethod
    def search(cls, query):
        # not sure why the if statement is the same as the expression,
        # this may be open for simplification (TODO)
        words = [word.strip() for word in query.split() if word.strip()]
        if not words:
            # return empty query
            return Entry.select().where(Entry.id == 0)
        else:
            search = ' '.join(words)

        # select -- selects all columns on Entry, and a score (the alias) to
        # the rank of each entry in matching the search string
        # .match - Generate a SQL expression representing a search for the given term or expression in the table.
        # order_by(SQL('score')) -- when using aliases, you must call them using
        # SQL(), which is a helper function that runs arbitrary SQL
        # NOTE: check this specification out for more info on what is supported
        # with match - http://sqlite.org/fts3.html#section_3
        return (Entry
                .select(Entry, FTSEntry.rank().alias('score'))
                .join(FTSEntry, on=(Entry.id == FTSEntry.docid))
                .where(
                    (Entry.published == True) &
                    (FTSEntry.match(search)))
                .order_by(SQL('score')))

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

# Implementing tags using the "Toxi" solution as suggested here:
# https://stackoverflow.com/a/20871
class Tag(flask_db.Model):

    title = CharField(unique=True)

    # TODO: add a method to sanaitize tag input

    @classmethod
    def search(cls, query):

        sanitized_query = re.sub('[^\w]+', '-', query.lower())

        return (Entry
                .select()
                .join(EntryTag)
                .where(EntryTag.tag == Tag.get(Tag.title == sanitized_query))
                .order_by(Entry.timestamp.desc()) )

class EntryTag(flask_db.Model):

    entry = ForeignKeyField(Entry, backref='tags')

    tag = ForeignKeyField(Tag, backref='entries')

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

        if request.headers.get('User-Agent') == app.config['UPLOADER_USER_AGENT']:
            return {'logged_in': False}, 403
        else:
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
    return Response(render_template('404.html')), 404


##################
# Routes
##################

@app.route('/login/', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next') or request.form.get('next')

    # if the user is submitting the password for authentication
    if request.method == 'POST' and request.form.get('password'):
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            # set the value in the cookie
            session['logged_in'] = True
            # store the cookie for more than this session
            session.permanent = True

            if request.headers.get('User-Agent') == app.config['UPLOADER_USER_AGENT']:
                return {'logged_in': True}, 200
            else:
                # flashes a message to the next request that can only be
                # retrieved by get_flashed_messages()
                flash('You are now logged in.', 'success')
                return redirect(next_url or url_for('index'))
        else:
            if request.headers.get('User-Agent') == app.config['UPLOADER_USER_AGENT']:
                return {'logged_in': False}, 403
            else:
                flash('Incorrect password.', 'danger')

    if request.headers.get('User-Agent') == app.config['UPLOADER_USER_AGENT']:
        return {'logged_in': False}, 403
    else:
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

@app.route('/')
def index(q=None, t=None):
    search_query = request.args.get('q') or q
    tag_search_query = request.args.get('t') or t
    if search_query:
        query = Entry.search(search_query)
    elif tag_search_query:
        query = Tag.search(tag_search_query)
    else:
        query = Entry.public().order_by(Entry.timestamp.desc())

    # object_list retrieves a paginated list of object in the query
    # and displays them using the template provided
    # by default, it paginates by 20 but this can be specified by a
    # variable paginate_by
    return object_list('index.html', query, search=search_query)

@app.route('/drafts/')
@login_required
def drafts():
    query = Entry.drafts().order_by(Entry.timestamp.desc())
    return object_list('index.html', query)

@app.route('/create/', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        if request.form.get('title') and request.form.get('content'):
            entry = Entry.create(
                title = request.form['title'],
                content = request.form['content'],
                published = request.form.get('published') or False)
            flash('Entry created successfully.', 'success')
            tags = [t.strip() for t in request.form['tags'].split(',')]
            (new_tags, new_entrytags) = entry.add_tags(*tags)
            flash(str(new_tags) + " new tags were created." )
            flash(str(new_entrytags) + " new entry tag relationships were created." )
            if entry.published:
                return redirect(url_for('detail', slug=entry.slug))
            else:
                return redirect(url_for('edit', slug=entry.slug))
        else:
            flash('Title and content are required.', 'danger')
    return render_template('create.html')

# Uploads a markdown file with headers from the blog_entry_uploader.py script
@app.route('/upload/', methods=['POST'])
@login_required
def upload():
    try:
        # ensure we are only uploading from the script
        assert(request.headers.get('User-Agent') == app.config['UPLOADER_USER_AGENT'])

        title = request.form.get('title')

        # cannot seem to find a better way to convert the string boolean into boolean
        published = True if request.form.get('published') == 'True' else False

        # opens the file in the request as a temporary file
        file = request.files['uploaded_file']
        # INFO: https://docs.python.org/3/library/tempfile.html#tempfile-examples
        file.stream.seek(0)

        # do not know if we are currently working on ascii only or on unicode
        content = file.stream.read().decode('ascii')

        entry = Entry.create(
            title = title,
            content = content,
            published = published)

        # code 201 -- requested resource has been created
        return {'file_uploaded': True}, 201

    except:
        # code 400 -- bad request
        return {'file_uploaded': False}, 400

@app.route('/tags/', methods=['GET'])
def list_tags():
    return render_template('tags.html', tags=[t.title for t in Tag.select()])

# in a flask route, anything <> is a variable and is passed on to the
# function defining the route
@app.route('/<slug>/')
def detail(slug):
    if session.get('logged_in'):
        query = Entry.select()
    else:
        query = Entry.public()
    # fairly self-defining  but I'm not sure what the 404 object is (TODO)
    entry = get_object_or_404(query, Entry.slug == slug)
    return render_template('detail.html', entry=entry)

@app.route('/<slug>/edit/', methods=['GET', 'POST'])
@login_required
def edit(slug):
    entry = get_object_or_404(Entry, Entry.slug == slug)
    if request.method == 'POST':
        if request.form.get('title') and request.form.get('content'):
            entry.title = request.form['title']
            entry.content = request.form['content']
            entry.published = request.form.get('published') or False
            entry.save()

            tags = [t.strip() for t in request.form['tags'].split(',')]
            (new_tags, new_entrytags) = entry.add_tags(*tags)

            flash(str(new_tags) + " new tags were created." )
            flash(str(new_entrytags) + " new entry tag relationships were created." )
            flash('Entry saved successfully.', 'success')
            if entry.published:
                return redirect(url_for('detail', slug=entry.slug))
            else:
                return redirect(url_for('edit', slug=entry.slug))
        else:
            flash('Title and content are required.', 'danger')

    return render_template('edit.html', entry=entry)

@app.route('/<slug>/delete/', methods=['POST'])
@login_required
def delete(slug):
    entry = get_object_or_404(Entry, Entry.slug == slug)

    try:
        entry.delete_instance()

        flash('Entry deleted.', 'success')

        return redirect(url_for('index'))
    except:
        flash('Entry not deleted.', 'danger')

        return redirect(url_for('edit', slug=slug))

##################
# App Initialization
##################

def main():
    # create tables if they don't already exist
    database.create_tables([Entry, FTSEntry, Tag, EntryTag])
    app.run(debug=True, host='0.0.0.0')

# hooo
if __name__ == '__main__':
    main()
