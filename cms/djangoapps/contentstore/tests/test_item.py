"""Tests for items views."""

import os
import json
import datetime
from pytz import UTC
import tempfile
from uuid import uuid4
from django.core.urlresolvers import reverse
from django.template.defaultfilters import slugify

from contentstore import utils
from contentstore.tests.utils import CourseTestCase
from cache_toolbox.core import del_cached_content
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.capa_module import CapaDescriptor
import json
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.inheritance import own_metadata
from cache_toolbox.core import del_cached_content
from xmodule.contentstore.django import contentstore
from xmodule.contentstore.content import StaticContent
from xmodule.exceptions import NotFoundError


class DeleteItem(CourseTestCase):
    """Tests for '/delete_item' url."""
    def setUp(self):
        """ Creates the test course with a static page in it. """
        super(DeleteItem, self).setUp()
        self.course = CourseFactory.create(org='mitX', number='333', display_name='Dummy Course')

    def test_delete_static_page(self):
        # Add static tab
        data = json.dumps({
            'parent_location': 'i4x://mitX/333/course/Dummy_Course',
            'category': 'static_tab'
        })

        resp = self.client.post(
            reverse('create_item'),
            data,
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)

        # Now delete it. There was a bug that the delete was failing (static tabs do not exist in draft modulestore).
        resp = self.client.post(
            reverse('delete_item'),
            resp.content,
            "application/json"
        )
        self.assertEqual(resp.status_code, 204)


class TestCreateItem(CourseTestCase):
    """
    Test the create_item handler thoroughly
    """
    def response_id(self, response):
        """
        Get the id from the response payload
        :param response:
        """
        parsed = json.loads(response.content)
        return parsed['id']

    def test_create_nicely(self):
        """
        Try the straightforward use cases
        """
        # create a chapter
        display_name = 'Nicely created'
        resp = self.client.post(
            reverse('create_item'),
            json.dumps({
                'parent_location': self.course.location.url(),
                'display_name': display_name,
                'category': 'chapter'
            }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)

        # get the new item and check its category and display_name
        chap_location = self.response_id(resp)
        new_obj = modulestore().get_item(chap_location)
        self.assertEqual(new_obj.scope_ids.block_type, 'chapter')
        self.assertEqual(new_obj.display_name, display_name)
        self.assertEqual(new_obj.location.org, self.course.location.org)
        self.assertEqual(new_obj.location.course, self.course.location.course)

        # get the course and ensure it now points to this one
        course = modulestore().get_item(self.course.location)
        self.assertIn(chap_location, course.children)

        # use default display name
        resp = self.client.post(
            reverse('create_item'),
            json.dumps({
                'parent_location': chap_location,
                'category': 'vertical'
            }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)

        vert_location = self.response_id(resp)

        # create problem w/ boilerplate
        template_id = 'multiplechoice.yaml'
        resp = self.client.post(
            reverse('create_item'),
            json.dumps({
                'parent_location': vert_location,
                'category': 'problem',
                'boilerplate': template_id
            }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        prob_location = self.response_id(resp)
        problem = modulestore('draft').get_item(prob_location)
        # ensure it's draft
        self.assertTrue(problem.is_draft)
        # check against the template
        template = CapaDescriptor.get_template(template_id)
        self.assertEqual(problem.data, template['data'])
        self.assertEqual(problem.display_name, template['metadata']['display_name'])
        self.assertEqual(problem.markdown, template['metadata']['markdown'])

    def test_create_item_negative(self):
        """
        Negative tests for create_item
        """
        # non-existent boilerplate: creates a default
        resp = self.client.post(
            reverse('create_item'),
            json.dumps(
                {'parent_location': self.course.location.url(),
                 'category': 'problem',
                 'boilerplate': 'nosuchboilerplate.yaml'
                 }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)


class TestEditItem(CourseTestCase):
    """
    Test contentstore.views.item.save_item
    """
    def response_id(self, response):
        """
        Get the id from the response payload
        :param response:
        """
        parsed = json.loads(response.content)
        return parsed['id']

    def setUp(self):
        """ Creates the test course structure and a couple problems to 'edit'. """
        super(TestEditItem, self).setUp()
        # create a chapter
        display_name = 'chapter created'
        resp = self.client.post(
            reverse('create_item'),
            json.dumps(
                {'parent_location': self.course.location.url(),
                 'display_name': display_name,
                 'category': 'chapter'
                 }),
            content_type="application/json"
        )
        chap_location = self.response_id(resp)
        resp = self.client.post(
            reverse('create_item'),
            json.dumps({
                'parent_location': chap_location,
                'category': 'sequential',
            }),
            content_type="application/json"
        )
        self.seq_location = self.response_id(resp)
        # create problem w/ boilerplate
        template_id = 'multiplechoice.yaml'
        resp = self.client.post(
            reverse('create_item'),
            json.dumps({
                'parent_location': self.seq_location,
                'category': 'problem',
                'boilerplate': template_id,
            }),
            content_type="application/json"
        )
        self.problems = [self.response_id(resp)]

    def test_delete_field(self):
        """
        Sending null in for a field 'deletes' it
        """
        self.client.post(
            reverse('save_item'),
            json.dumps({
                'id': self.problems[0],
                'metadata': {'rerandomize': 'onreset'}
            }),
            content_type="application/json"
        )
        problem = modulestore('draft').get_item(self.problems[0])
        self.assertEqual(problem.rerandomize, 'onreset')
        self.client.post(
            reverse('save_item'),
            json.dumps({
                'id': self.problems[0],
                'metadata': {'rerandomize': None}
            }),
            content_type="application/json"
        )
        problem = modulestore('draft').get_item(self.problems[0])
        self.assertEqual(problem.rerandomize, 'never')

    def test_null_field(self):
        """
        Sending null in for a field 'deletes' it
        """
        problem = modulestore('draft').get_item(self.problems[0])
        self.assertIsNotNone(problem.markdown)
        self.client.post(
            reverse('save_item'),
            json.dumps({
                'id': self.problems[0],
                'nullout': ['markdown']
            }),
            content_type="application/json"
        )
        problem = modulestore('draft').get_item(self.problems[0])
        self.assertIsNone(problem.markdown)

    def test_date_fields(self):
        """
        Test setting due & start dates on sequential
        """
        sequential = modulestore().get_item(self.seq_location)
        self.assertIsNone(sequential.due)
        self.client.post(
            reverse('save_item'),
            json.dumps({
                'id': self.seq_location,
                'metadata': {'due': '2010-11-22T04:00Z'}
            }),
            content_type="application/json"
        )
        sequential = modulestore().get_item(self.seq_location)
        self.assertEqual(sequential.due, datetime.datetime(2010, 11, 22, 4, 0, tzinfo=UTC))
        self.client.post(
            reverse('save_item'),
            json.dumps({
                'id': self.seq_location,
                'metadata': {'start': '2010-09-12T14:00Z'}
            }),
            content_type="application/json"
        )
        sequential = modulestore().get_item(self.seq_location)
        self.assertEqual(sequential.due, datetime.datetime(2010, 11, 22, 4, 0, tzinfo=UTC))
        self.assertEqual(sequential.start, datetime.datetime(2010, 9, 12, 14, 0, tzinfo=UTC))


class Basetranscripts(CourseTestCase):
    """Base test class for transcripts tests."""

    org = 'MITx'
    number = '999'

    def clear_subs_content(self):
        """Remove, if transcripts content exists."""
        for youtube_id in self.get_youtube_ids().values():
            filename = 'subs_{0}.srt.sjson'.format(youtube_id)
            content_location = StaticContent.compute_location(
                self.org, self.number, filename)
            try:
                content = contentstore().find(content_location)
                contentstore().delete(content.get_id())
            except NotFoundError:
                pass

    def setUp(self):
        """Create initial data."""
        super(Basetranscripts, self).setUp()

        # Add video module
        data = {
            'parent_location': str(self.course_location),
            'category': 'video',
            'type': 'video'
        }
        resp = self.client.post(reverse('create_item'), data)
        self.item_location = json.loads(resp.content).get('id')
        self.assertEqual(resp.status_code, 200)

        # hI10vDNYz4M - valid Youtube ID with transcripts.
        # JMD_ifUUfsU, AKqURZnYqpk, DYpADpL7jAY - valid Youtube IDs
        # without transcripts.
        data = '<video youtube="0.75:JMD_ifUUfsU,1.0:hI10vDNYz4M,1.25:AKqURZnYqpk,1.50:DYpADpL7jAY" />'
        modulestore().update_item(self.item_location, data)

        self.item = modulestore().get_item(self.item_location)

        # Remove all transcripts for current module.
        self.clear_subs_content()

    def get_youtube_ids(self):
        """Return youtube speeds and ids."""
        item = modulestore().get_item(self.item_location)

        return {
            0.75: item.youtube_id_0_75,
            1: item.youtube_id_1_0,
            1.25: item.youtube_id_1_25,
            1.5: item.youtube_id_1_5
        }


class TestImporttranscriptsFromYoutube(Basetranscripts):
    """Tests for saving video item."""

    def test_success_video_module_subs_importing(self):
        # Import transcripts.
        resp = self.client.post(
            reverse('save_item'), {'id': self.item_location, 'metadata': {}})

        self.assertEqual(resp.status_code, 204)

        # Check assets status after importing transcripts.
        for youtube_id in self.get_youtube_ids().values():
            filename = 'subs_{0}.srt.sjson'.format(youtube_id)
            content_location = StaticContent.compute_location(
                self.org, self.number, filename)
            self.assertTrue(contentstore().find(content_location))

    def test_fail_youtube_ids_unavailable(self):
        data = '<video youtube="0.75:BAD_YOUTUBE_ID1,1:BAD_YOUTUBE_ID2,1.25:BAD_YOUTUBE_ID3,1.5:BAD_YOUTUBE_ID4" />'
        modulestore().update_item(self.item_location, data)

        # Import transcripts.
        resp = self.client.post(
            reverse('save_item'), {'id': self.item_location, 'metadata': {}})

        self.assertEqual(resp.status_code, 204)

        for youtube_id in self.get_youtube_ids().values():
            filename = 'subs_{0}.srt.sjson'.format(youtube_id)
            content_location = StaticContent.compute_location(
                self.org, self.number, filename)
            self.assertRaises(
                NotFoundError, contentstore().find, content_location)

    def tearDown(self):
        super(TestImporttranscriptsFromYoutube, self).tearDown()

        # Remove all transcripts for current module.
        self.clear_subs_content()


class TestUploadtranscripts(Basetranscripts):
    """Tests for '/upload_transcripts' url."""

    def setUp(self):
        """Create initial data."""
        super(TestUploadtranscripts, self).setUp()

        self.good_srt_file = tempfile.NamedTemporaryFile(suffix='.srt')
        self.good_srt_file.write("""
1
00:00:10,500 --> 00:00:13,000
Elephant's Dream

2
00:00:15,000 --> 00:00:18,000
At the left we can see...
        """)
        self.good_srt_file.seek(0)

        self.bad_data_srt_file = tempfile.NamedTemporaryFile(suffix='.srt')
        self.bad_data_srt_file.write('Some BAD data')
        self.bad_data_srt_file.seek(0)

        self.bad_name_srt_file = tempfile.NamedTemporaryFile(suffix='.BAD')
        self.bad_name_srt_file.write("""
1
00:00:10,500 --> 00:00:13,000
Elephant's Dream

2
00:00:15,000 --> 00:00:18,000
At the left we can see...
        """)
        self.bad_name_srt_file.seek(0)

    def test_success_video_module_source_subs_uploading(self):
        data = """
<video youtube="">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
"""
        modulestore().update_item(self.item_location, data)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(json.loads(resp.content).get('success'))

        filename = slugify(
            os.path.splitext(os.path.basename(self.good_srt_file.name))[0])
        item = modulestore().get_item(self.item_location)
        self.assertEqual(item.sub, filename)

        content_location = StaticContent.compute_location(
            self.org, self.number, 'subs_{0}.srt.sjson'.format(filename))
        self.assertTrue(contentstore().find(content_location))

    def test_fail_video_module_youtube_subs_uploading(self):
        # Check assets status before uploading transcripts.
        for youtube_id in self.get_youtube_ids().values():
            filename = 'subs_{0}.srt.sjson'.format(youtube_id)
            content_location = StaticContent.compute_location(
                self.org, self.number, filename)
            self.assertRaises(
                NotFoundError, contentstore().find, content_location)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

        item = modulestore().get_item(self.item_location)
        self.assertEqual(item.sub, '')

        # Check assets status after uploading transcripts.
        for youtube_id in self.get_youtube_ids().values():
            filename = 'subs_{0}.srt.sjson'.format(youtube_id)
            content_location = StaticContent.compute_location(
                self.org, self.number, filename)
            self.assertRaises(
                NotFoundError, contentstore().find, content_location)

    def test_fail_data_without_id(self):
        resp = self.client.post(
            reverse('upload_transcripts'), {'file': self.good_srt_file})

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_data_without_file(self):
        resp = self.client.post(
            reverse('upload_transcripts'), {'id': self.item_location})

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_data_with_bad_location(self):
        # Test for raising `InvalidLocationError` exception.
        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': 'BAD_LOCATION',
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

        # Test for raising `ItemNotFoundError` exception.
        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': '{0}_{1}'.format(self.item_location, 'BAD_LOCATION'),
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_for_non_video_module(self):
        # Videoalpha module: setup
        data = {
            'parent_location': str(self.course_location),
            'category': 'videoalpha',
            'type': 'videoalpha'
        }
        resp = self.client.post(reverse('create_item'), data)
        item_location = json.loads(resp.content).get('id')
        data = '<videoalpha youtube="0.75:JMD_ifUUfsU,1.0:hI10vDNYz4M" />'
        modulestore().update_item(item_location, data)

        # Videoalpha module: testing
        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': item_location,
                'file': self.good_srt_file
            })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_bad_xml(self):
        data = '<<<video youtube="0.75:JMD_ifUUfsU,1.25:AKqURZnYqpk,1.50:DYpADpL7jAY" />'
        modulestore().update_item(self.item_location, data)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_miss_youtube_and_source_attrs(self):
        data = """
<video youtube="">
    <source src=""/>
</video>
"""
        modulestore().update_item(self.item_location, data)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

        data = '<video />'
        modulestore().update_item(self.item_location, data)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.good_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_bad_data_srt_file(self):
        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.bad_data_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_bad_name_srt_file(self):
        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': self.bad_name_srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_undefined_file_extension(self):
        srt_file = tempfile.NamedTemporaryFile(suffix='')
        srt_file.write("""
1
00:00:10,500 --> 00:00:13,000
Elephant's Dream

2
00:00:15,000 --> 00:00:18,000
At the left we can see...
        """)
        srt_file.seek(0)

        resp = self.client.post(
            reverse('upload_transcripts'),
            {
                'id': self.item_location,
                'file': srt_file
            })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def tearDown(self):
        super(TestUploadtranscripts, self).tearDown()

        self.good_srt_file.close()
        self.bad_data_srt_file.close()
        self.bad_name_srt_file.close()


class TestDownloadtranscripts(Basetranscripts):
    """Tests for '/download_transcripts' url."""

    def save_subs_to_store(self, subs, subs_id):
        """Save transcripts into `StaticContent`."""
        filedata = json.dumps(subs, indent=2)
        mime_type = 'application/json'
        filename = 'subs_{0}.srt.sjson'.format(subs_id)

        content_location = StaticContent.compute_location(
            self.org, self.number, filename)
        content = StaticContent(content_location, filename, mime_type, filedata)
        contentstore().save(content)
        del_cached_content(content_location)
        return content_location

    def remove_subs_from_store(self, subs_id):
        """Remove from store, if transcripts content exists."""
        filename = 'subs_{0}.srt.sjson'.format(subs_id)
        content_location = StaticContent.compute_location(
            self.org, self.number, filename)
        try:
            content = contentstore().find(content_location)
            contentstore().delete(content.get_id())
        except NotFoundError:
            pass

    def test_fail_download_youtube(self):
        data = '<video youtube="1:JMD_ifUUfsU" />'
        modulestore().update_item(self.item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, 'JMD_ifUUfsU')

        resp = self.client.get(
            reverse('download_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 404)

    def test_success_download_nonyoutube(self):
        subs_id = str(uuid4())
        data = """
<video youtube="" sub="{}">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
""".format(subs_id)
        modulestore().update_item(self.item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, subs_id)

        resp = self.client.get(
            reverse('download_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 200)

        utils.remove_subs_from_store(subs_id, self.item)

    def test_fail_data_without_file(self):
        resp = self.client.get(
            reverse('download_transcripts'), {'id': ''})
        self.assertEqual(resp.status_code, 404)

        resp = self.client.get(
            reverse('download_transcripts'), {})
        self.assertEqual(resp.status_code, 404)

    def test_fail_data_with_bad_location(self):
        # Test for raising `InvalidLocationError` exception.
        resp = self.client.get(
            reverse('download_transcripts'), {'id': 'BAD_LOCATION'})
        self.assertEqual(resp.status_code, 404)

        # Test for raising `ItemNotFoundError` exception.
        resp = self.client.get(
            reverse('download_transcripts'),
            {'id': '{0}_{1}'.format(self.item_location, 'BAD_LOCATION')})
        self.assertEqual(resp.status_code, 404)

    def test_fail_for_non_video_module(self):
        # Video module: setup
        data = {
            'parent_location': str(self.course_location),
            'category': 'videoalpha',
            'type': 'videoalpha'
        }
        resp = self.client.post(reverse('create_item'), data)
        item_location = json.loads(resp.content).get('id')
        subs_id = str(uuid4())
        data = """
<videoalpha youtube="" sub="{}">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</videoalpha>
""".format(subs_id)
        modulestore().update_item(item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, subs_id)

        resp = self.client.get(
            reverse('download_transcripts'), {'id': item_location})
        self.assertEqual(resp.status_code, 404)

    def test_fail_nonyoutube_subs_dont_exist(self):
        data = """
<video youtube="" sub="UNDEFINED">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
"""
        modulestore().update_item(self.item_location, data)

        resp = self.client.get(
            reverse('download_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 404)

    def test_empty_youtube_attr_and_sub_attr(self):
        data = """
<video youtube="">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
"""
        modulestore().update_item(self.item_location, data)

        resp = self.client.get(
            reverse('download_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 404)

    def test_fail_bad_sjson_subs(self):
        subs_id = str(uuid4())
        data = """
<video youtube="" sub="{}">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
""".format(subs_id)
        modulestore().update_item(self.item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1'
            ]
        }
        self.save_subs_to_store(subs, 'JMD_ifUUfsU')

        resp = self.client.get(
            reverse('download_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 404)


class TestChecktranscripts(Basetranscripts):
    """Tests for '/check_transcripts' url."""

    def save_subs_to_store(self, subs, subs_id):
        """Save transcripts into `StaticContent`."""
        filedata = json.dumps(subs, indent=2)
        mime_type = 'application/json'
        filename = 'subs_{0}.srt.sjson'.format(subs_id)

        content_location = StaticContent.compute_location(
            self.org, self.number, filename)
        content = StaticContent(content_location, filename, mime_type, filedata)
        contentstore().save(content)
        del_cached_content(content_location)
        return content_location

    def remove_subs_from_store(self, subs_id):
        """Remove from store, if transcripts content exists."""
        filename = 'subs_{0}.srt.sjson'.format(subs_id)
        content_location = StaticContent.compute_location(
            self.org, self.number, filename)
        try:
            content = contentstore().find(content_location)
            contentstore().delete(content.get_id())
        except NotFoundError:
            pass

    def test_success_download_nonyoutube(self):
        subs_id = str(uuid4())
        data = """
<video youtube="" sub="{}">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
""".format(subs_id)
        modulestore().update_item(self.item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, subs_id)

        resp = self.client.post(
            reverse('check_transcripts'), {
                'id': self.item_location,
                'video_id': subs_id
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertDictEqual(
            json.loads(resp.content),
            {u'status': u'Success', u'youtube_server': False, u'html5_local': True, u'youtube_local': False}
        )

        utils.remove_subs_from_store(subs_id, self.item)

    def test_fail_check_youtube(self):
        data = '<video youtube="1:JMD_ifUUfsU" />'
        modulestore().update_item(self.item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, 'JMD_ifUUfsU')

        resp = self.client.get(
            reverse('check_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_data_without_file(self):
        resp = self.client.get(
            reverse('check_transcripts'), {'id': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

        resp = self.client.get(
            reverse('check_transcripts'), {})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_data_with_bad_location(self):
        # Test for raising `InvalidLocationError` exception.
        resp = self.client.get(
            reverse('check_transcripts'), {'id': 'BAD_LOCATION'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

        # Test for raising `ItemNotFoundError` exception.
        resp = self.client.get(
            reverse('check_transcripts'),
            {'id': '{0}_{1}'.format(self.item_location, 'BAD_LOCATION')})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_for_non_video_module(self):
        # Video module: setup
        data = {
            'parent_location': str(self.course_location),
            'category': 'videoalpha',
            'type': 'videoalpha'
        }
        resp = self.client.post(reverse('create_item'), data)
        item_location = json.loads(resp.content).get('id')
        subs_id = str(uuid4())
        data = """
<videoalpha youtube="" sub="{}">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</videoalpha>
""".format(subs_id)
        modulestore().update_item(item_location, data)

        subs = {
            'start': [100, 200, 240],
            'end': [200, 240, 380],
            'text': [
                'subs #1',
                'subs #2',
                'subs #3'
            ]
        }
        self.save_subs_to_store(subs, subs_id)

        resp = self.client.get(
            reverse('check_transcripts'), {'id': item_location})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_fail_nonyoutube_subs_dont_exist(self):
        data = """
<video youtube="" sub="UNDEFINED">
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.mp4"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.webm"/>
    <source src="http://www.quirksmode.org/html5/videos/big_buck_bunny.ogv"/>
</video>
"""
        modulestore().update_item(self.item_location, data)

        resp = self.client.get(
            reverse('check_transcripts'), {'id': self.item_location})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(json.loads(resp.content).get('success'))
