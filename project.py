from flask import Flask
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import jsonify
from flask import flash
from sqlalchemy import create_engine
from sqlalchemy import desc
from sqlalchemy.orm import sessionmaker
from database_setup1 import Base
from database_setup1 import Categories
from database_setup1 import Items
from database_setup1 import User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Catalog App"

engine = create_engine('sqlite:///sportingequipment.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
# This code was copied from the Udacity restaurant project
@app.route('/login')
def showLogin():
    state = ''.join(
        random.choice(string.ascii_uppercase + string.digits)
        for x in range(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


# This code was copied from the Udacity restaurant project
@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code, now compatible with Python3
    request.get_data()
    code = request.data.decode('utf-8')

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    # Submit request, parse response - Python3 compatible
    h = httplib2.Http()
    response = h.request(url, 'GET')[1]
    str_response = response.decode('utf-8')
    result = json.loads(str_response)

    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps(
                                'Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ''' " style = "width: 300px; height: 300px;border-radius:
                    150px;-webkit-border-radius: 150px;
                    -moz-border-radius: 150px;"> '''
    flash("you are now logged in as %s" % login_session['username'])
    return output


# User Helper Functions
# This code was copied from the Udacity restaurant project
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session
# This code was copied from the Udacity restaurant project
@app.route('/gdisconnect')
def gdisconnect():
        # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        # Reset the user's sesson.
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# homepage of catalog app. Displays all categories and the most recent items
@app.route('/')
def category_list():
    categories = session.query(Categories).all()
    q = session.query(Categories, Items).join(Items).\
        order_by(desc(Items.id)).limit(10)
    return render_template('index.html', categories=categories,  q=q)


# allows the user to create a new item
@app.route('/newitem/', methods=['GET', 'POST'])
def new_item():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newItem = Items(title=request.form['title'],
                        description=request.form['description'],
                        cat_id=request.form['category'],
                        user_id=login_session['user_id'])
        session.add(newItem)
        session.commit()
        return redirect(url_for('category_list'))
    else:
        categories = session.query(Categories).all()
        return render_template('new_item.html', categories=categories)


# allows for editing an existing item, assuming user was the item creator
@app.route('/<string:category_name>/<string:item_name>/edit/',
           methods=['GET', 'POST'])
def edit_item(category_name, item_name):
    category = session.query(Categories).\
        filter_by(name=category_name).first()
    editedItem = session.query(Items).\
        filter_by(cat_id=category.id, title=item_name).first()
    if 'username' not in login_session:
        return redirect('/login')
    if editedItem.user_id != login_session['user_id']:
        return """<script>function myFunction()
        {alert('You are not authorized to edit this item.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        editedItem.title = request.form['title']
        editedItem.description = request.form['description']
        session.commit()
        flash('Item Successfully Edited: %s' % editedItem.title)
        return redirect(url_for('category_list'))
    else:
        item = session.query(Items).filter_by(title=item_name).first()
        return render_template('edit_item.html', category=category, item=item)


# allows user to delete an item
@app.route('/<string:category_name>/<string:item_name>/delete/',
           methods=['GET', 'POST'])
def delete_item(category_name, item_name):
    category = session.query(Categories).filter_by(name=category_name).first()
    itemToDelete = session.query(Items).\
        filter_by(cat_id=category.id, title=item_name).first()
    if 'username' not in login_session:
        return redirect('/login')
    if itemToDelete.user_id != login_session['user_id']:
        return """<script>function myFunction()
        {alert('You are not authorized to delete this item.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Item Successfully Deleted: %s' % itemToDelete.title)
        return redirect(url_for('category_list'))
    else:
        item = session.query(Items).filter_by(title=item_name).first()
        return render_template('delete_item.html',
                               category=category, item=item)


# lists items per category
@app.route('/<string:name>/')
def item_list(name):
    items = []
    categories = session.query(Categories).all()
    category = session.query(Categories).filter_by(name=name).first()
    if category:
        items = session.query(Items).filter_by(cat_id=category.id).all()
    return render_template('items_by_category.html', items=items,
                           categories=categories, category=category)


# displays item detail with links to edit/delete
@app.route('/<string:category_name>/<string:item_name>/')
def item_detail(category_name, item_name):
    category = session.query(Categories).filter_by(name=category_name).first()
    item = session.query(Items).\
        filter_by(cat_id=category.id, title=item_name).first()
    return render_template('item_detail.html', item=item, category=category)


# Category Edit was used for debug only; not used in production app
@app.route('/categories/<int:category_id>/', methods=['GET', 'POST'])
def category_edit(category_id):
    category = session.query(Categories).filter_by(id=category_id).one()
    if request.method == 'POST':
        category.name = (request.form['name'])
        session.commit()
        return redirect(url_for('category_list'))
    else:
        return render_template('category_edit.html', category=category)


# allows user to add a new category
@app.route('/newcategory/', methods=['GET', 'POST'])
def new_category():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newCategory = Categories(name=request.form['name'],
                                 user_id=login_session['user_id'])
        session.add(newCategory)
        session.commit()
        return redirect(url_for('category_list'))
    else:
        return render_template('category_new.html')


# JSON APIs to view catagories and associated items
# Code help from: https://discussions.udacity.com
# /t/how-do-you-jsonify-a-master-detail-database-structure/17080/2
@app.route('/catalog.json/')
def catalogJSON():
    categories = session.query(Categories).all()
    serializedCategories = []
    for i in categories:
        serializedItems = []
        new_cat = i.serialize
        items = session.query(Items).filter_by(cat_id=i.id).all()
        for j in items:
            serializedItems.append(j.serialize)
        new_cat['items'] = serializedItems
        serializedCategories.append(new_cat)
    return jsonify(serializedCategories)


# JSON API to view all items in a category:
@app.route('/<string:category_name>/catalog.json')
def itemByCategoryJSON(category_name):
    category = session.query(Categories).filter_by(name=category_name).first()
    items = session.query(Items).\
        filter_by(cat_id=category.id).all()
    return jsonify(items=[i.serialize for i in items])


# JSON API to view item detail:
@app.route('/<string:category_name>/<string:item_name>/catalog.json')
def itemCatalogJSON(category_name, item_name):
    category = session.query(Categories).filter_by(name=category_name).first()
    item = session.query(Items).\
        filter_by(cat_id=category.id, title=item_name).first()
    return jsonify(item.serialize)


if __name__ == '__main__':
    app.secret_key = '2KGMYpBfQa_YXBxLnHMkE2-6'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
