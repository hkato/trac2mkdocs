import argparse
import re
import sqlite3
from datetime import datetime
from hashlib import sha1
from os import makedirs, path
from shutil import copy

from git import Actor, Repo

from . import trac2down

TRAC_DB_PATH = 'db/trac.db'
ATTACHMENTS_PATH = 'files/attachments/wiki'
TRAC2DOWN_UPLOADS = '/uploads/migrated'
IMAGE_PATH = 'images'
EXCLUDE_PAGES = [
    'CamelCase',
    'InterMapTxt',
    'InterTrac',
    'InterWiki',
    'PageTemplates',
    'RecentChanges',
    'SandBox',
    'TicketQuery',
    'TitleIndex',
    'TracAccessibility',
    'TracAdmin',
    'TracBackup',
    'TracBatchModify',
    'TracBrowser',
    'TracCgi',
    'TracChangeLog',
    'TracChangeset',
    'TracEnvironment',
    'TracFastCgi',
    'TracFineGrainedPermissions',
    'TracGuide',
    'TracImport',
    'TracIni',
    'TracInstall',
    'TracInterfaceCustomization',
    'TracJa',
    'TracLinks',
    'TracLogging',
    'TracModPython',
    'TracModWSGI',
    'TracNavigation',
    'TracNotification',
    'TracPermissions',
    'TracPlugins',
    'TracQuery',
    'TracReports',
    'TracRepositoryAdmin',
    'TracRevisionLog',
    'TracRoadmap',
    'TracRss',
    'TracSearch',
    'TracStandalone',
    'TracSupport',
    'TracSyntaxColoring',
    'TracTickets',
    'TracTicketsCustomFields',
    'TracTimeline',
    'TracUnicode',
    'TracUpgrade',
    'TracWiki',
    'TracWorkflow',
    'WikiDeletePage',
    'WikiFormatting',
    'WikiHtml',
    'WikiMacros',
    'WikiNewPage',
    'WikiPageNames',
    'WikiProcessors',
    'WikiRestructuredText',
    'WikiRestructuredTextLinks',
]
REPLACE_PAGES = {
    'WikiStart': 'index'
}


class Trac2MkDocs():

    def __init__(self, project_path, pages_path, author_file):
        self.project_path = project_path
        self.pages_path = pages_path
        self.author_file = author_file
        self.conn = sqlite3.connect(path.join(project_path, TRAC_DB_PATH))
        self.authors = dict()
        self.__create_commit_list()
        if (self.__create_author_file(author_file)):
            print('Edit {0} file before converting.'.format(author_file))
            exit()
        self.__create_author_file(author_file)

    def convert(self):
        image_path = path.join(self.pages_path, IMAGE_PATH)
        makedirs(image_path, exist_ok=True)

        self.__get_authors(self.author_file)
        repo = Repo.init(self.pages_path)

        cursor = self.conn.cursor()
        contents = cursor.execute(
            'SELECT type, login, time, name FROM temp.content ORDER BY time ASC;')

        for content in contents:
            type = content[0]
            login = content[1]
            time = content[2]
            filename = content[3]
            commit_date = datetime.fromtimestamp(
                time/1000000).strftime('%Y-%m-%d %H:%M:%S')
            author = Actor(self.authors[login]['name'],
                           self.authors[login]['email'])

            cursor = self.conn.cursor()

            if type == 'wiki':
                wiki = cursor.execute(
                    'SELECT name, version, text FROM wiki \
                        WHERE time = ? AND name = ? AND author = ?;',
                    (time, filename, login)).fetchone()
                name = wiki[0]
                if name not in EXCLUDE_PAGES:
                    if name in REPLACE_PAGES:
                        name = REPLACE_PAGES.get(name)
                    version = wiki[1]
                    text = wiki[2]
                    filename = name + '.md'
                    with open(path.join(self.pages_path, filename), mode='w') as f:
                        markdown = trac2down.convert(text, name)
                        markdown = self.__mkdocs_convert(markdown)
                        f.write(markdown)
                    if (version == 1):
                        message = 'Add version {1}'.format(name, version)
                    else:
                        message = 'Update version {1}'.format(name, version)
                    repo.index.add(filename)
                    print(commit_date, login, name, message)
                    repo.index.commit(message, author=author,
                                      commit_date=commit_date, author_date=commit_date)

            elif type == 'attachment':
                attachment = cursor.execute(
                    'SELECT filename, id, description FROM attachment \
                        WHERE time = ? AND filename = ? AND author = ?;',
                    (time, filename, login)).fetchone()
                filename = attachment[0]
                id = attachment[1]
                attachment_path = self.__get_attachment_path(id, filename)
                message = 'Upload attachment'
                try:
                    copy(attachment_path, path.join(image_path, filename))
                    repo.index.add(IMAGE_PATH)
                except FileNotFoundError:
                    pass
                print(commit_date, login, filename, message)
                repo.index.commit(message, author=author,
                                  commit_date=commit_date, author_date=commit_date)

    def __create_commit_list(self):
        cursor1 = self.conn.cursor()
        cursor2 = self.conn.cursor()
        cursor1.execute(
            'CREATE TABLE temp.content(type TEXT, login TEXT, time INT, name TEXT);')

        wikis = cursor1.execute('SELECT author, time, name FROM wiki;')
        for wiki in wikis:
            login = wiki[0]
            time = wiki[1]
            name = wiki[2]
            cursor2.execute(
                'INSERT INTO temp.content (type, login, time, name) values(?, ?, ?, ?);',
                ('wiki', login, time, name))

        attachments = cursor1.execute(
            'SELECT author, time, filename FROM attachment;')
        for attachment in attachments:
            login = attachment[0]
            time = attachment[1]
            filename = attachment[2]
            cursor2.execute(
                'INSERT INTO temp.content (type, login, time, name) values(?, ?, ?, ?);',
                ('attachment', login, time, filename))

    def __create_author_file(self, author_file):
        if (path.exists(author_file)):
            return False
        cursor = self.conn.cursor()
        logins = cursor.execute(
            'SELECT DISTINCT login FROM temp.content ORDER BY time ASC;')

        with open(author_file, 'w') as f:
            for login in logins:
                f.write(login[0] + ' = \n')

        return True

    def __get_authors(self, author_file):
        with open(author_file, 'r') as f:
            lines = f.readlines()
            for line in lines:
                try:
                    author = re.match(r'(.*) = (.*) <(.*)>', line)
                    login = author.groups()[0]
                    name = author.groups()[1]
                    email = author.groups()[2]
                    self.authors[login] = {'name': name, 'email': email}
                except Exception:
                    raise Exception(
                        'File format error: fix {0}'.format(author_file))

    def __get_attachment_path(self, id, filename):
        path2 = sha1(id.encode('utf-8')).hexdigest()
        path1 = path2[0:3]
        basename, ext = path.splitext(filename)
        file_hash = sha1(filename.encode('utf-8')).hexdigest() + ext
        attachment_path = path.join(
            self.project_path, ATTACHMENTS_PATH, path1, path2, file_hash)
        return attachment_path

    def __mkdocs_convert(self, content):
        content = re.sub(r'(.*?)(' + re.escape(TRAC2DOWN_UPLOADS) + r')(.*?)',
                         r'\1' + re.escape(IMAGE_PATH) + r'\3', content)
        content = re.sub(r'\[\[(.*?)\]\]', r'[\1](../\1)', content)

        return content


def cli():
    parser = argparse.ArgumentParser(description='Trac wiki to Markdown pages')
    parser.add_argument('project_path', help='Trac project path')
    parser.add_argument('--pages_path', default='./docs',
                        help='Markdown pages path')
    parser.add_argument('--author-file', default='./authors.txt',
                        help='Author file same as git-svn')
    args = parser.parse_args()
    project_path = args.project_path
    pages_path = args.pages_path
    author_file = args.author_file

    trac2mkdocs = Trac2MkDocs(project_path, pages_path, author_file)
    trac2mkdocs.convert()
