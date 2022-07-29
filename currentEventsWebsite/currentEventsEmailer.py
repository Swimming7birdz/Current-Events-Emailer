import feedparser
from bs4 import BeautifulSoup
import urllib
from dateparser import parse as parse_date
import requests
import re
import time

import os
from trycourier import Courier

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf import FlaskForm
from flask_wtf import Form
from wtforms import SubmitField, StringField, SelectField, IntegerField
from wtforms.validators import data_required, length, NumberRange



#--------------------------------------------------------------------------------------------------------------------------#
class GoogleNews:
    def __init__(self, lang = 'en', country = 'US'):
        self.lang = lang.lower()
        self.country = country.upper()
        self.BASE_URL = 'https://news.google.com/rss'

    def __top_news_parser(self, text):
        """Return subarticles from the main and topic feeds"""
        try:
            bs4_html = BeautifulSoup(text, "html.parser")
            # find all li tags
            lis = bs4_html.find_all('li')
            sub_articles = []
            for li in lis:
                try:
                    sub_articles.append({"url": li.a['href'],
                                         "title": li.a.text,
                                         "publisher": li.font.text})
                except:
                    pass
            return sub_articles
        except:
            return text

    def __ceid(self):
        """Compile correct country-lang parameters for Google News RSS URL"""
        return '?ceid={}:{}&hl={}&gl={}'.format(self.country,self.lang,self.lang,self.country)

    def __add_sub_articles(self, entries):
        for i, val in enumerate(entries):
            if 'summary' in entries[i].keys():
                entries[i]['sub_articles'] = self.__top_news_parser(entries[i]['summary'])
            else:
                entries[i]['sub_articles'] = None
        return entries

    def __scaping_bee_request(self, api_key, url):
        response = requests.get(
            url="https://app.scrapingbee.com/api/v1/",
            params={
                "api_key": api_key,
                "url": url,
                "render_js": "false"
            }
        )
        if response.status_code == 200:
            return response
        if response.status_code != 200:
            raise Exception("ScrapingBee status_code: "  + str(response.status_code) + " " + response.text)

    def __parse_feed(self, feed_url, proxies=None, scraping_bee = None):

        if scraping_bee and proxies:
            raise Exception("Pick either ScrapingBee or proxies. Not both!")

        if proxies:
            r = requests.get(feed_url, proxies = proxies)
        else:
            r = requests.get(feed_url)

        if scraping_bee:
            r = self.__scaping_bee_request(url = feed_url, api_key = scraping_bee)
        else:
            r = requests.get(feed_url)


        if 'https://news.google.com/rss/unsupported' in r.url:
            raise Exception('This feed is not available')

        d = feedparser.parse(r.text)

        if not scraping_bee and not proxies and len(d['entries']) == 0:
            d = feedparser.parse(feed_url)

        return dict((k, d[k]) for k in ('feed', 'entries'))

    def __search_helper(self, query):
        return urllib.parse.quote_plus(query)

    def __from_to_helper(self, validate=None):
        try:
            validate = parse_date(validate).strftime('%Y-%m-%d')
            return str(validate)
        except:
            raise Exception('Could not parse your date')



    def top_news(self, proxies=None, scraping_bee = None):
        """Return a list of all articles from the main page of Google News
        given a country and a language"""
        d = self.__parse_feed(self.BASE_URL + self.__ceid(), proxies=proxies, scraping_bee=scraping_bee)
        d['entries'] = self.__add_sub_articles(d['entries'])
        return d

    def topic_headlines(self, topic: str, proxies=None, scraping_bee=None):
        """Return a list of all articles from the topic page of Google News
        given a country and a language"""
        #topic = topic.upper()
        if topic.upper() in ['WORLD', 'NATION', 'BUSINESS', 'TECHNOLOGY', 'ENTERTAINMENT', 'SCIENCE', 'SPORTS', 'HEALTH']:
            d = self.__parse_feed(self.BASE_URL + '/headlines/section/topic/{}'.format(topic.upper()) + self.__ceid(), proxies = proxies, scraping_bee=scraping_bee)

        else:
            d = self.__parse_feed(self.BASE_URL + '/topics/{}'.format(topic) + self.__ceid(), proxies = proxies, scraping_bee=scraping_bee)

        d['entries'] = self.__add_sub_articles(d['entries'])
        if len(d['entries']) > 0:
            return d
        else:
            raise Exception('unsupported topic')

    def geo_headlines(self, geo: str, proxies=None, scraping_bee=None):
        """Return a list of all articles about a specific geolocation
        given a country and a language"""
        d = self.__parse_feed(self.BASE_URL + '/headlines/section/geo/{}'.format(geo) + self.__ceid(), proxies = proxies, scraping_bee=scraping_bee)

        d['entries'] = self.__add_sub_articles(d['entries'])
        return d

    def search(self, query: str, helper = True, when = None, from_ = None, to_ = None, proxies=None, scraping_bee=None):
        """
        Return a list of all articles given a full-text search parameter,
        a country and a language
        :param bool helper: When True helps with URL quoting
        :param str when: Sets a time range for the artiles that can be found
        """

        if when:
            query += ' when:' + when

        if from_ and not when:
            from_ = self.__from_to_helper(validate=from_)
            query += ' after:' + from_

        if to_ and not when:
            to_ = self.__from_to_helper(validate=to_)
            query += ' before:' + to_

        if helper == True:
            query = self.__search_helper(query)

        search_ceid = self.__ceid()
        search_ceid = search_ceid.replace('?', '&')

        d = self.__parse_feed(self.BASE_URL + '/search?q={}'.format(query) + search_ceid, proxies = proxies, scraping_bee=scraping_bee)

        d['entries'] = self.__add_sub_articles(d['entries'])
        return d


#--------------------------------------------------------------------------------------------------------------------------------------#

app = Flask(__name__)
app.secret_key = "5^h4ads#;kj:x@I"

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://ghysyusemjrzur:e20d31961e07dc565de6be6e8177a3db7a6a150bf61cd9f78c5739219871d903@ec2-44-206-214-233.compute-1.amazonaws.com:5432/ddd5kb0t7ri2g7'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class Info(db.Model):
    __tablename__= 'info'
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(200), nullable = False)
    content = db.Column(db.String(), nullable = False)
    lang = db.Column(db.String(200), nullable = False)
    country = db.Column(db.String(200), nullable = False)
    

@app.route('/', methods = ['GET', 'POST'])
def index():
    if request.method == 'POST':
        if request.form['submit_button'] == 'Begin':
            return redirect(url_for('mainPg'))
        
    return render_template('indexHome.html')


class NameForm(FlaskForm):
    username = StringField('', validators = [data_required(),length(min = 1)])
    submit = SubmitField('Submit')


@app.route('/mainPg', methods = ['POST', 'GET'])
def mainPg():
        
    form = NameForm()
    if form.validate_on_submit():
        nm = form.username.data
        
        new_option = Info(id = 1, name = nm, content = '', lang = '', country = '')
        
        db.session.add(new_option)
        db.session.commit()
        
        return redirect(url_for('general'))
            
    return render_template('mainPg.html', form=form)


class MultipleForm(FlaskForm):
    newsType = SelectField('', choices = [('1', '1. unlimited search'), ('2', '2. unlimited top news'),('3', '3. unlimited topic headlines'),('4', '4. unlimited geographic headlines'),('5', '5. limited general search'),('6', '6. limited top news'),('7', '7. limited topic headlines'),('8', '8. limited geographic headlines')], default=1, coerce=int, validators=[data_required()])
    lang = SelectField('', choices = [('1', 'English / United States'), ('2', 'Español / Estados Unidos'),('3', 'Français / France métroopolitaine'),('4', 'Italiano / Italia')], default=1, coerce=int, validators=[data_required()])
    submit = SubmitField('Submit')


@app.route('/general', methods = ['POST', 'GET'])
def general():

    form = MultipleForm()
    if request.method == 'POST' and form.validate():
        newsType = form.newsType.data
        langCount = form.lang.data

        
        languagesList = ['en', 'es', 'fr', 'it']
        countryList = ['United States', 'United States', 'France', 'Italy']

        lang = languagesList[langCount-1]
        country = countryList[langCount-1]

        # if there's already an entry with an id of 1, delete it and add new entry with id of 1
        
        new_option = Info(id = 2, name = '', content = '', lang = lang, country = country) 
        
        db.session.add(new_option)
        db.session.commit()
            

        if (newsType == 1):
            return redirect(url_for('optionOne'))
            
        elif (newsType == 2):
            return redirect(url_for('optionTwo'))
            
        elif (newsType == 3):
            return redirect(url_for('optionThree'))

        elif (newsType == 4):
            return redirect(url_for('optionFour'))
                    
        elif (newsType == 5):
            return redirect(url_for('optionFive'))
        
        elif (newsType == 6):
            return redirect(url_for('optionSix'))
            
        elif (newsType == 7):
            return redirect(url_for('optionSeven'))
        
        elif (newsType == 8):
            return redirect(url_for('optionEight'))

    return render_template('general.html', form=form)

        
class OptionOneForm(FlaskForm):
    search = StringField('', validators = [data_required(), length(min = 2)])
    submit = SubmitField('Submit')

@app.route("/optionOne", methods = ['GET', 'POST'])
def optionOne():

    form = OptionOneForm()
    if request.method == 'POST' and form.validate():        
        search = form.search.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertString(get_titlesAndLinksSearchUnlimited(search,gn))
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')

        db.session.add(new_content)
        db.session.commit()

        
        return redirect(url_for('emailSend'))

    return render_template('optionOne.html',form=form)


@app.route("/optionTwo", methods = ['GET', 'POST'])
def optionTwo():
    
    gn_option = Info.query.filter_by(id = 2).first()
    gn = GoogleNews(gn_option.lang, gn_option.country)

    bodyText = convertString(get_titlesAndLinksTopNewsUnlimited(gn))
        
    new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')

    
    db.session.add(new_content)
    db.session.commit()
                     
    
    return redirect(url_for('emailSend')) 


class OptionThreeForm(FlaskForm):
    topic = SelectField('', choices = [('world','World'),('nation','Nation'),('technology','Technology'),('business','Business'),('entertainment','Entertainment'),('science','Science'),('sports','Sports'),('health','Health')])
    submit = SubmitField('Submit')

@app.route("/optionThree", methods = ['GET', 'POST'])
def optionThree():
    
    form = OptionThreeForm()
    if request.method == 'POST' and form.validate():         
        topic = form.topic.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertString(get_titlesAndLinksTopicHeadlinesUnlimited(topic,gn))
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')

        db.session.add(new_content)
        db.session.commit()

        
        return redirect(url_for('emailSend'))

    return render_template('optionThree.html',form=form)


class OptionFourForm(FlaskForm):
    location = StringField('', validators = [data_required(), length(min = 4)])
    submit = SubmitField('Submit')

@app.route("/optionFour", methods = ['GET', 'POST'])
def optionFour():

    form = OptionFourForm()
    if request.method == 'POST' and form.validate():         
        location = form.location.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertString(get_titlesAndLinksGeoHeadlinesUnlimited(location,gn))
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')

        db.session.add(new_content)
        db.session.commit()
            
        
        return redirect(url_for('emailSend'))

    return render_template('optionFour.html',form=form)


class OptionFiveForm(FlaskForm):
    search = StringField('', validators = [data_required(), length(min = 1)])
    number = IntegerField('', validators = [data_required(), NumberRange(min = 1)]) 
    submit = SubmitField('Submit')

@app.route("/optionFive", methods = ['GET', 'POST'])
def optionFive():
    
    form = OptionFiveForm()
    if request.method == 'POST' and form.validate():    
        search = form.search.data
        number = form.number.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertStringLimited(get_titlesAndLinksSearch(search,number,gn), number)
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')

        db.session.add(new_content)
        db.session.commit()
            
        
        return redirect(url_for('emailSend'))

    return render_template('optionFive.html',form=form)


class OptionSixForm(FlaskForm):
    number = IntegerField('', validators = [data_required(), NumberRange(min = 1)]) 
    submit = SubmitField('Submit')

@app.route("/optionSix", methods = ['GET', 'POST'])
def optionSix():
    
    form = OptionSixForm()
    if request.method == 'POST' and form.validate():
        number = form.number.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertStringLimited(get_titlesAndLinksTopNews(number,gn), number)
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')


        db.session.add(new_content)
        db.session.commit()
            
    
        
        return redirect(url_for('emailSend'))

    return render_template('optionSix.html',form=form)


class OptionSevenForm(FlaskForm):
    topic = SelectField('', choices = [('world','World'),('nation','Nation'),('technology','Technology'),('business','Business'),('entertainment','Entertainment'),('science','Science'),('sports','Sports'),('health','Health')])
    number = IntegerField('', validators = [data_required(), NumberRange(min = 1)]) 
    submit = SubmitField('Submit')

@app.route("/optionSeven", methods = ['GET', 'POST'])
def optionSeven():
    
    form = OptionSevenForm()
    if request.method == 'POST' and form.validate():
        topic = form.topic.data
        number = form.number.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertStringLimited(get_titlesAndLinksTopicHeadlines(topic,number,gn), number)
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')


        db.session.add(new_content)
        db.session.commit()
            
        
        
        return redirect(url_for('emailSend'))

    return render_template('optionSeven.html',form=form)


class OptionEightForm(FlaskForm):
    location = StringField('', validators = [data_required(), length(min = 4)])
    number = IntegerField('', validators = [data_required(), NumberRange(min = 1)]) 
    submit = SubmitField('Submit')


@app.route("/optionEight", methods = ['GET', 'POST'])
def optionEight():
    
    form = OptionEightForm()
    if request.method == 'POST' and form.validate():
        location = form.location.data
        number = form.number.data
        
        gn_option = Info.query.filter_by(id = 2).first()
        gn = GoogleNews(gn_option.lang, gn_option.country)
        
        bodyText = convertStringLimited(get_titlesAndLinksGeoHeadlines(location,number,gn), number)
        
        new_content = Info(id = 3, name = '', content = bodyText, lang = '', country = '')


        db.session.add(new_content)
        db.session.commit()
            

        
        return redirect(url_for('emailSend'))

    return render_template('optionEight.html',form=form)

        
def unlimitedAppend(newsitem): #returns a list of the titles, time of publication, and link
    sourceList = []
    
    lang_option = Info.query.filter_by(id = 2).first()
    language = lang_option.lang

    if (language == 'en'):
        for item in newsitem:
            source = 'Title: ' + item.title + '\n'\
                     '\n'\
                     'Published: ' + item.published + '\n'\
                     '\n'\
                     'Link: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)
    
    elif (language == 'es'):
        for item in newsitem:
            source = 'Título: ' + item.title + '\n'\
                     '\n'\
                     'Publicado: ' + item.published + '\n'\
                     '\n'\
                     'Enlace de página web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)


    elif (language == 'fr'):
        for item in newsitem:
            source = 'Titre: ' + item.title + '\n'\
                     '\n'\
                     'Publié: ' + item.published + '\n'\
                     '\n'\
                     'Lien de site web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)


    elif (language == 'it'):
        for item in newsitem:
            source = 'Titolo: ' + item.title + '\n'\
                     '\n'\
                     'Pubblicato: ' + item.published + '\n'\
                     '\n'\
                     'Collegamento al sito web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)

    
    return sourceList
         

def limitedAppend(num, newsitem): #returns a list of the titles, time of publication, and link
    sourceList = []
    
    lang_option = Info.query.filter_by(id = 2).first()
    language = lang_option.lang

    if (language == 'en'):
        for item in newsitem[:num]:
            source = 'Title: ' + item.title + '\n'\
                     '\n'\
                     'Published: ' + item.published + '\n'\
                     '\n'\
                     'Link: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)
    
    elif (language == 'es'):
        for item in newsitem[:num]:
            source = 'Título: ' + item.title + '\n'\
                     '\n'\
                     'Publicado: ' + item.published + '\n'\
                     '\n'\
                     'Enlace de página web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)


    elif (language == 'fr'):
        for item in newsitem[:num]:
            source = 'Titre: ' + item.title + '\n'\
                     '\n'\
                     'Publié: ' + item.published + '\n'\
                     '\n'\
                     'Lien de site web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)


    elif (language == 'it'):
        for item in newsitem[:num]:
            source = 'Titolo: ' + item.title + '\n'\
                     '\n'\
                     'Pubblicato: ' + item.published + '\n'\
                     '\n'\
                     'Collegamento al sito web: ' + item.link + '\n'\
                     '\n'\
                     '\n'\
                     ' ' 
            sourceList.append(source)

    return sourceList


def get_titlesAndLinksSearchUnlimited(search,gn):
    return unlimitedAppend(gn.search(search)['entries'])


def get_titlesAndLinksSearch(search, num, gn):
    return limitedAppend(num, gn.search(search)['entries'])


def get_titlesAndLinksTopNewsUnlimited(gn):
    return unlimitedAppend(gn.top_news()['entries'])


def get_titlesAndLinksTopNews(num, gn):
    return limitedAppend(num, gn.top_news()['entries'])


def get_titlesAndLinksTopicHeadlinesUnlimited(topics, gn):
    return unlimitedAppend(gn.topic_headlines(topics)['entries'])


def get_titlesAndLinksTopicHeadlines(topics, num, gn):
    return limitedAppend(num, gn.topic_headlines(topics)['entries'])


def get_titlesAndLinksGeoHeadlinesUnlimited(location, gn):
    return unlimitedAppend(gn.geo_headlines(location)['entries'])


def get_titlesAndLinksGeoHeadlines(location, num, gn):    
    return limitedAppend(num, gn.geo_headlines(location)['entries'])



def convertString(listTitles): #makes list into string, also numbers each article for unlimited
    counter = 1
    text = ''
    
    lang_option = Info.query.filter_by(id = 2).first()
    language = lang_option.lang
    message = ''

    if (language == 'en'):
        for item in listTitles:
            if (item[:5] == 'Title'):
                number = str(counter) + '.'
                counter += 1
            
            package = number + item
            
            text += package

    elif (language == 'es'):
        for item in listTitles:
            if (item[:6] == 'Título'):
                number = str(counter) + '.'
                counter += 1
            
            package = number + item
        
            text += package


    elif (language == 'fr'):
        for item in listTitles:
            if (item[:5] == 'Titre'):
                number = str(counter) + '.'
                counter += 1
            
            package = number + item
        
            text += package

    elif (language == 'it'):
        for item in listTitles:
            if (item[:6] == 'Titolo'):
                number = str(counter) + '.'
                counter += 1
            
            package = number + item
        
            text += package

    
    return '\n' + text


def convertStringLimited(listTitles, num): #makes list into string, also numbers each article for limited
    counter = 1
    text = ''
    message = ''

    lang_option = Info.query.filter_by(id = 2).first()
    language = lang_option.lang
    

    if (language == 'en'):
        for item in listTitles:
            if (item[:5] == 'Title'):
                number = str(counter) + '.'
                counter += 1
                
            package = number + item
            text += package

        
        if(num > counter):
            diff = (num - counter) + 1
            message = '\nSorry Google News has ' + str(diff) + ' less articles than you requested, which was: ' + str(num)+ '\n\n'


    elif (language == 'es'):
        for item in listTitles:
            if (item[:6] == 'Título'):
                number = str(counter) + '.'
                counter += 1
                
            package = number + item
            text += package

        
        if(num > counter):
            diff = (num - counter) + 1
            message = '\nLo siento, las noticias de Google tenían ' + str(diff) + ' artículos menos de los que solicitaste, que eran: ' + str(num)+ '\n\n'


    elif (language == 'fr'): 
        for item in listTitles:
            if (item[:5] == 'Titre'):
                number = str(counter) + '.'
                counter += 1
                
            package = number + item
            text += package

        
        if(num > counter):
            diff = (num - counter) + 1
            message = '\nDésolé, Google Actualités contient ' + str(diff) + ' articles de moins que ce que vous avez demandé, soit: ' + str(num)+ '\n\n'


    elif (language == 'it'):
        for item in listTitles:
            if (item[:6] == 'Titolo'):
                number = str(counter) + '.'
                counter += 1
                
            package = number + item
            text += package

        
        if(num > counter):
            diff = (num - counter) + 1
            message = '\nSpiacenti, Google News ha ' + str(diff) + ' articoli in meno di quelli che hai richiesto, ovvero: ' + str(num)+ '\n\n'



        
    message += text
      
    return message


    


class EmailForm(FlaskForm):
    email = StringField('', validators = [data_required(), length(min=1)])
    submit = SubmitField('Submit')

@app.route("/emailSend", methods = ['GET', 'POST'])
def emailSend():

    form = EmailForm()

    nm_content = Info.query.filter_by(id = 1).first()
    name = nm_content.name
    
    lang_option = Info.query.filter_by(id = 2).first()
    language = lang_option.lang
    title = ''

    if (language == 'en'):
        title = 'This is your GoogleNews update '
    elif (language == 'es'):
        title = 'Esta es tu actualización de Google News '
    elif (language == 'fr'):
        title = 'Ceci est votre mise à jour Google Actualités '
    elif (language == 'it'):
        title = 'Questo è il tuo aggiornamento di GoogleNews '
    
    gn_content = Info.query.filter_by(id = 3).first()
    bodyText = gn_content.content
    
    if request.method == 'POST':        
        email = form.email.data
        client = Courier(auth_token="pk_prod_X4BZPAXBRV4P7MHCW27TFH6YPAKM") #or set via COURIER_AUTH_TOKEN env var

        resp = client.send_message(
          message={
            'to': {
              'email': email,
              'data': {'name': name}
            },
            'content': {
              'title': title + name,
              'body': bodyText, 
            },
            'routing': {
              'method': 'single',
              'channels': ['email'],
            }
          }
        )
        
        return redirect(url_for('endPg'))
    
    return render_template('emailSend.html',form=form)

        
@app.route("/endPg", methods = ['GET', 'POST'])
def endPg():
     
    if request.method == 'POST':
        if request.form['submit_button'] == 'Home':
            return render_template('indexHome.html')
        
        elif request.form['submit_button'] == 'Questions Page':
            return render_template('questionsPg.html')

        elif request.form['submit_button'] == 'Restart':
            return redirect(url_for('mainPg'))
 
    Info.query.filter_by(id = 1).delete()
    db.session.commit()
    Info.query.filter_by(id = 2).delete()
    db.session.commit()
    Info.query.filter_by(id = 3).delete()
    db.session.commit()


    return render_template('endPg.html')


@app.route("/questionsPg")
def questionsPg():
    return render_template('questionsPg.html')

@app.route("/aboutPg")
def aboutPg():
    return render_template('aboutPg.html')

#------------------------------------------------------------------------------------------------------------------------#


if __name__ == "__main__":
    app.debug = True
    app.run()

# if not working add: host = '0.0.0.0', debug=True, run, then delete, then run without host

