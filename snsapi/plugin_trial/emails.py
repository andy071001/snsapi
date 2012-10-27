#-*- encoding: utf-8 -*-

'''
email platform

Support get message by IMAP and send message by SMTP

The file is named as "emails.py" instead of "email.py"
because there is a package in Python called "email". 
We will import that package..

'''

from ..snslog import SNSLog
logger = SNSLog
from ..snsbase import SNSBase
from .. import snstype
from ..utils import console_output
from .. import utils
from ..utils import json

import time
import email
import imaplib
import smtplib

logger.debug("%s plugged!", __file__)

class Email(SNSBase):
    class Message(snstype.Message):
        def parse(self):
            self.ID.platform = self.platform
            self._parse(self.raw)

        def _parse(self, dct):
            #TODO:
            #    Put in message id. 
            #    The id should be composed of mailbox and id in the box.
            #
            #    The IMAP id can not be used as a global identifier. 
            #    Once messages are deleted or moved, it will change. 
            #    The IMAP id is more like the subscript of an array. 
            #    
            #    SNSAPI should work out its own message format to store an 
            #    identifier. An identifier should be (address, sequence). 
            #    There are three ways to generate the sequence number: 
            #       * 1. Random pick
            #       * 2. Pass message through a hash
            #       * 3. Maintain a counter in the mailbox 
            #       * 4. UID as mentioned in some discussions. Not sure whether
            #       this is account-dependent or not. 
            #
            #     I prefer 2. at present. Our Message objects are designed 
            #     to be able to digest themselves. 
            self.parsed.title = dct.get('Subject')
            self.parsed.text = dct.get('Subject')
            self.parsed.time = utils.str2utc(dct.get('Date'))
            self.parsed.username = dct.get('From')
            self.parsed.userid = dct.get('From')

    def __init__(self, channel = None):
        super(Email, self).__init__(channel)

        self.platform = self.__class__.__name__
        self.Message.platform = self.platform

        self.imap = None
        self.smtp = None

    @staticmethod
    def new_channel(full = False):
        c = SNSBase.new_channel(full)

        c['platform'] = 'Email'
        c['imap_host'] = 'imap.gmail.com'
        c['imap_port'] = 993 #default IMAP + TLS port
        c['smtp_host'] = 'smtp.gmail.com'
        c['smtp_port'] = 587 #default SMTP + TLS port 
        c['username'] = 'username'
        c['password'] = 'password'
        c['address'] = 'username@gmail.com'
        return c
        
    def read_channel(self, channel):
        super(Email, self).read_channel(channel) 

    def _extract_body(self, payload):
        #TODO:
        #    Extract and decode if necessary. 
        if isinstance(payload,str):
            return payload
        else:
            return '\n'.join([self._extract_body(part.get_payload()) for part in payload])

    def _wait_for_email_subject(self, sub):
        conn = self.imap
        conn.select('INBOX')
        num = None
        while (num is None):
            logger.debug("num is None")
            typ, data = conn.search(None, '(Subject "%s")' % sub)
            num = data[0].split()[0]
            time.sleep(0.5)
        return num
    
    def _get_buddy_list(self):
        (typ, data) = self.imap.create('buddy')

        conn = self.imap
        conn.select('buddy')

        self.buddy_list = []
        num = None
        self._buddy_message_id = None
        try:
            typ, data = conn.search(None, 'ALL')
            # We support multiple emails in "buddy" folder. 
            # Each of the files contain a json list. We'll 
            # merge all the list and use it as the buddy_list. 
            for num in data[0].split():
                typ, msg_data = conn.fetch(num, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_string(response_part[1])
                        text = self._extract_body(msg.get_payload())
                        logger.debug("Extract part text '%s' failed!", text)
                        try:
                            self.buddy_list.extend(json.loads(text))
                        except Exception, e:
                            logger.warning("Extend list with '%s' failed!", e)
            logger.debug("reading buddylist successful: %s", self.buddy_list)
        except Exception, e:
            logger.warning("catch exception when trying to read buddylist %s", e)
            pass

        if self.buddy_list is None:
            logger.debug("buddy list is None")
            self.buddy_list = []

    def _update_buddy_list(self):
        conn = self.imap

        # The unique identifier for a buddy_list
        title = 'buddy_list:' + str(self.time())
        from email.mime.text import MIMEText
        msg = MIMEText(json.dumps(self.buddy_list))
        self._send(self.jsonconf['address'], title, msg)

        # Wait for the new buddy_list email to arrive
        mlist = self._wait_for_email_subject(title)
        logger.debug("returned message id: %s", mlist)

        # Clear obsolete emails in "buddy" box
        conn.select('buddy')
        typ, data = conn.search(None, 'ALL')
        for num in data[0].split():
            conn.store(num, '+FLAGS', r'(\deleted)')
            logger.debug("deleting message '%s' from 'buddy'", num)

        # Move the new buddy_list email from INBOX to "buddy" box
        conn.select('INBOX')
        conn.copy(mlist, 'buddy')
        conn.store(mlist, '+FLAGS', r'(\deleted)')


    def _receive(self):
        conn = self.imap
        conn.select('INBOX')
        typ, data = conn.search(None, 'ALL')
        l = []
        try:
            for num in data[0].split():
                typ, msg_data = conn.fetch(num, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_string(response_part[1])
                        #print msg['Content-Type']
                        #payload=msg.get_payload()
                        #body=extract_body(payload)
                        #print(body)

                        # Convert header fields into dict
                        d = dict(msg) 
                        # Add other essential fields
                        d['body'] = self._extract_body(msg.get_payload())
                        d['_pyobj'] = utils.Serialize.dumps(msg)
                        l.append(utils.JsonDict(d))
                #typ, response = conn.store(num, '+FLAGS', r'(\Seen)')
        finally:
            pass
            #try:
            #    conn.close()
            #except:
            #    pass
            ##conn.logout()
        return l

    def auth(self):
        imap_ok = False
        smtp_ok = False

        logger.debug("Try loggin IMAP server...")
        try:
            if self.imap:
                del self.imap
            self.imap = imaplib.IMAP4_SSL(self.jsonconf['imap_host'], self.jsonconf['imap_port'])
            self.imap.login(self.jsonconf['username'], self.jsonconf['password'])
            imap_ok = True
        except imaplib.IMAP4_SSL.error, e:
            if e.message.find("AUTHENTICATIONFAILED"):
                logger.warning("IMAP Authentication failed! Channel '%s'", self.jsonconf['channel_name'])
            else:
                raise e
        
        logger.debug("Try loggin SMTP server...")
        try:
            if self.smtp:
                del self.smtp
            self.smtp = smtplib.SMTP("%s:%s" % (self.jsonconf['smtp_host'], self.jsonconf['smtp_port']))  
            self.smtp.starttls()  
            self.smtp.login(self.jsonconf['username'], self.jsonconf['password'])
            smtp_ok = True
        except smtplib.SMTPAuthenticationError:
            logger.warning("SMTP Authentication failed! Channel '%s'", self.jsonconf['channel_name'])

        if imap_ok and smtp_ok:
            logger.info("Email channel '%s' auth success", self.jsonconf['channel_name'])
            self._get_buddy_list()
            #self._update_buddy_list()
            return True
        else:
            logger.warning("Email channel '%s' auth failed!!", self.jsonconf['channel_name'])
            return False
            

    def _send(self, toaddr, title, msg):
        '''
        :param toaddr:
            The recipient, only one in a string. 

        :param msg:
            One email object, which supports as_string() method
        '''
        fromaddr = self.jsonconf['address']
        msg['From'] = fromaddr
        msg['To'] = toaddr
        msg['Subject'] = title

        try:
            self.smtp.sendmail(fromaddr, toaddr, msg.as_string())  
            return True
        except Exception, e:
            logger.warning("%s", str(e)) 
            return False


    def home_timeline(self, count = 20):
        r = self._receive()

        message_list = []
        for m in r:
            message_list.append(self.Message(
                    m,\
                    platform = self.jsonconf['platform'],\
                    channel = self.jsonconf['channel_name']\
                    ))

        return message_list


    def update(self, text):
        from email.mime.text import MIMEText
        msg = MIMEText(text, _charset = 'utf-8')
        return self._send('hpl1989@gmail.com', 'test from snsapi', msg)

# === email message fields for future reference
# TODO:
#     Enhance the security level by check fields like 
#     'Received'. GMail has its checking at the web 
#     interface side. Fraud identity problem will be 
#     alleviated. 
# In [7]: msg.keys()
# Out[7]: 
# ['Delivered-To',
# 'Received',
# 'Received',
# 'Return-Path',
# 'Received',
# 'Received-SPF',
# 'Authentication-Results',
# 'Received',
# 'DKIM-Signature',
# 'MIME-Version',
# 'Received',
# 'X-Notifications',
# 'X-UB',
# 'X-All-Senders-In-Circles',
# 'Date',
# 'Message-ID',
# 'Subject',
# 'From',
# 'To',
# 'Content-Type']
# 
# In [8]: msg['From']
# Out[8]: '"Google+ team" <noreply-daa26fef@plus.google.com>'
# 
# In [9]: msg['To']
# Out[9]: 'hupili.snsapi@gmail.com'
# 
# In [10]: msg['Subject']
# Out[10]: 'Getting started on Google+'
# 
# In [11]: msg['Date']
# Out[11]: 'Mon, 22 Oct 2012 22:37:37 -0700 (PDT)'
# 
# In [12]: msg['Content-Type']
# Out[12]: 'multipart/alternative; boundary=047d7b5dbe702bc3f804ccb35e18'