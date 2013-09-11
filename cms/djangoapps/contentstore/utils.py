#pylint: disable=E1103, E1101

from __future__ import division

import copy
import logging
import re
import json
import HTMLParser
import StringIO
from functools import wraps
from lxml import etree

import requests
from pysrt import SubRipTime, SubRipItem, SubRipFile

from django.conf import settings
from django.utils.translation import ugettext as _
from django_comment_client.utils import JsonResponse

from cache_toolbox.core import del_cached_content
from xmodule.contentstore.content import StaticContent
from xmodule.contentstore.django import contentstore
from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.inheritance import own_metadata
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.modulestore.draft import DIRECT_ONLY_CATEGORIES
from xmodule.exceptions import NotFoundError


log = logging.getLogger(__name__)

# In order to instantiate an open ended tab automatically, need to have this data
OPEN_ENDED_PANEL = {"name": _("Open Ended Panel"), "type": "open_ended"}
NOTES_PANEL = {"name": _("My Notes"), "type": "notes"}
EXTRA_TAB_PANELS = dict([(p['type'], p) for p in [OPEN_ENDED_PANEL, NOTES_PANEL]])


def get_modulestore(category_or_location):
    """
    Returns the correct modulestore to use for modifying the specified location
    """
    if isinstance(category_or_location, Location):
        category_or_location = category_or_location.category

    if category_or_location in DIRECT_ONLY_CATEGORIES:
        return modulestore('direct')
    else:
        return modulestore()


def get_course_location_for_item(location):
    '''
    cdodge: for a given Xmodule, return the course that it belongs to
    NOTE: This makes a lot of assumptions about the format of the course location
    Also we have to assert that this module maps to only one course item - it'll throw an
    assert if not
    '''
    item_loc = Location(location)

    # check to see if item is already a course, if so we can skip this
    if item_loc.category != 'course':
        # @hack! We need to find the course location however, we don't
        # know the 'name' parameter in this context, so we have
        # to assume there's only one item in this query even though we are not specifying a name
        course_search_location = ['i4x', item_loc.org, item_loc.course, 'course', None]
        courses = modulestore().get_items(course_search_location)

        # make sure we found exactly one match on this above course search
        found_cnt = len(courses)
        if found_cnt == 0:
            raise Exception('Could not find course at {0}'.format(course_search_location))

        if found_cnt > 1:
            raise Exception('Found more than one course at {0}. There should only be one!!! Dump = {1}'.format(course_search_location, courses))

        location = courses[0].location

    return location


def get_course_for_item(location):
    '''
    cdodge: for a given Xmodule, return the course that it belongs to
    NOTE: This makes a lot of assumptions about the format of the course location
    Also we have to assert that this module maps to only one course item - it'll throw an
    assert if not
    '''
    item_loc = Location(location)

    # @hack! We need to find the course location however, we don't
    # know the 'name' parameter in this context, so we have
    # to assume there's only one item in this query even though we are not specifying a name
    course_search_location = ['i4x', item_loc.org, item_loc.course, 'course', None]
    courses = modulestore().get_items(course_search_location)

    # make sure we found exactly one match on this above course search
    found_cnt = len(courses)
    if found_cnt == 0:
        raise BaseException('Could not find course at {0}'.format(course_search_location))

    if found_cnt > 1:
        raise BaseException('Found more than one course at {0}. There should only be one!!! Dump = {1}'.format(course_search_location, courses))

    return courses[0]


def get_lms_link_for_item(location, preview=False, course_id=None):
    """
    Returns an LMS link to the course with a jump_to to the provided location.

    :param location: the location to jump to
    :param preview: True if the preview version of LMS should be returned. Default value is false.
    :param course_id: the course_id within which the location lives. If not specified, the course_id is obtained
           by calling Location(location).course_id; note that this only works for locations representing courses
           instead of elements within courses.
    """
    if course_id is None:
        course_id = Location(location).course_id

    if settings.LMS_BASE is not None:
        if preview:
            lms_base = settings.MITX_FEATURES.get('PREVIEW_LMS_BASE')
        else:
            lms_base = settings.LMS_BASE

        lms_link = "//{lms_base}/courses/{course_id}/jump_to/{location}".format(
            lms_base=lms_base,
            course_id=course_id,
            location=Location(location)
        )
    else:
        lms_link = None

    return lms_link


def get_lms_link_for_about_page(location):
    """
    Returns the url to the course about page from the location tuple.
    """
    if settings.MITX_FEATURES.get('ENABLE_MKTG_SITE', False):
        if not hasattr(settings, 'MKTG_URLS'):
            log.exception("ENABLE_MKTG_SITE is True, but MKTG_URLS is not defined.")
            about_base = None
        else:
            marketing_urls = settings.MKTG_URLS
            if marketing_urls.get('ROOT', None) is None:
                log.exception('There is no ROOT defined in MKTG_URLS')
                about_base = None
            else:
                # Root will be "https://www.edx.org". The complete URL will still not be exactly correct,
                # but redirects exist from www.edx.org to get to the Drupal course about page URL.
                about_base = marketing_urls.get('ROOT')
                # Strip off https:// (or http://) to be consistent with the formatting of LMS_BASE.
                about_base = re.sub(r"^https?://", "", about_base)
    elif settings.LMS_BASE is not None:
        about_base = settings.LMS_BASE
    else:
        about_base = None

    if about_base is not None:
        lms_link = "//{about_base_url}/courses/{course_id}/about".format(
            about_base_url=about_base,
            course_id=Location(location).course_id
        )
    else:
        lms_link = None

    return lms_link


def course_image_url(course):
    """Returns the image url for the course."""
    loc = course.location._replace(tag='c4x', category='asset', name=course.course_image)
    path = StaticContent.get_url_path_from_location(loc)
    return path


class UnitState(object):
    draft = 'draft'
    private = 'private'
    public = 'public'


def compute_unit_state(unit):
    """
    Returns whether this unit is 'draft', 'public', or 'private'.

    'draft' content is in the process of being edited, but still has a previous
        version visible in the LMS
    'public' content is locked and visible in the LMS
    'private' content is editabled and not visible in the LMS
    """

    if getattr(unit, 'is_draft', False):
        try:
            modulestore('direct').get_item(unit.location)
            return UnitState.draft
        except ItemNotFoundError:
            return UnitState.private
    else:
        return UnitState.public


def update_item(location, value):
    """
    If value is None, delete the db entry. Otherwise, update it using the correct modulestore.
    """
    if value is None:
        get_modulestore(location).delete_item(location)
    else:
        get_modulestore(location).update_item(location, value)


def add_extra_panel_tab(tab_type, course):
    """
    Used to add the panel tab to a course if it does not exist.
    @param tab_type: A string representing the tab type.
    @param course: A course object from the modulestore.
    @return: Boolean indicating whether or not a tab was added and a list of tabs for the course.
    """
    # Copy course tabs
    course_tabs = copy.copy(course.tabs)
    changed = False
    # Check to see if open ended panel is defined in the course

    tab_panel = EXTRA_TAB_PANELS.get(tab_type)
    if tab_panel not in course_tabs:
        # Add panel to the tabs if it is not defined
        course_tabs.append(tab_panel)
        changed = True
    return changed, course_tabs


def remove_extra_panel_tab(tab_type, course):
    """
    Used to remove the panel tab from a course if it exists.
    @param tab_type: A string representing the tab type.
    @param course: A course object from the modulestore.
    @return: Boolean indicating whether or not a tab was added and a list of tabs for the course.
    """
    # Copy course tabs
    course_tabs = copy.copy(course.tabs)
    changed = False
    # Check to see if open ended panel is defined in the course

    tab_panel = EXTRA_TAB_PANELS.get(tab_type)
    if tab_panel in course_tabs:
        # Add panel to the tabs if it is not defined
        course_tabs = [ct for ct in course_tabs if ct != tab_panel]
        changed = True
    return changed, course_tabs


def return_ajax_status(view_function):
    """Except, that view function return True/False, and convert
    response to JSON HTTP response:
        {"success": true} or {"success": false}
    """
    @wraps(view_function)
    def new_view_function(request, *args, **kwargs):
        """New view functions for decorator result."""
        result = view_function(request, *args, **kwargs)
        if isinstance(result, tuple):
            status = result[0]
            response_data = result[1]
        else:
            status = result
            response_data = {}
        response_data.update({'success': status})
        return JsonResponse(response_data)
    return new_view_function


def generate_subs(speed, source_speed, source_subs):
    """Generate and return transcripts dictionary for speed equal to
    `speed` value, using `source_speed` and `source_subs`."""
    if speed == source_speed:
        return source_subs

    coefficient = speed / source_speed
    subs = {
        'start': [
            int(round(timestamp * coefficient)) for
            timestamp in source_subs['start']
        ],
        'end': [
            int(round(timestamp * coefficient)) for
            timestamp in source_subs['end']
        ],
        'text': source_subs['text']}
    return subs


def save_subs_to_store(subs, subs_id, item):
    """Save transcripts into `StaticContent`."""
    filedata = json.dumps(subs, indent=2)
    mime_type = 'application/json'
    filename = 'subs_{0}.srt.sjson'.format(subs_id)

    content_location = StaticContent.compute_location(
        item.location.org, item.location.course, filename)
    content = StaticContent(content_location, filename, mime_type, filedata)
    contentstore().save(content)
    del_cached_content(content_location)
    return content_location


def download_youtube_subs(youtube_subs, item):
    """Download transcripts from Youtube using `youtube_ids`, and
    save them to assets for `item` module."""
    html_parser = HTMLParser.HTMLParser()
    status_dict = {}

    # Iterate from lowest to highest speed and try to do download transcripts
    # from the Youtube service.
    for speed, youtube_id in sorted(youtube_subs.iteritems()):
        if not youtube_id:
            continue

        data = requests.get(
            "http://video.google.com/timedtext",
            params={'lang': 'en', 'v': youtube_id})

        if data.status_code != 200 or not data.text:
            status_dict.update({speed: False})
            log.error("Can't recieved correct transcripts from Youtube.")
            continue

        sub_starts = []
        sub_ends = []
        sub_texts = []

        xmltree = etree.fromstring(str(data.text))
        for element in xmltree:
            if element.tag == "text":
                start = float(element.get("start"))
                duration = float(element.get("dur"))
                text = element.text
                end = start + duration

                if text:
                    # Start and end are an int representing the
                    # millisecond timestamp.
                    sub_starts.append(int(start * 1000))
                    sub_ends.append(int((end + 0.0001) * 1000))
                    sub_texts.append(
                        html_parser.unescape(text.replace('\n', ' ')))

        available_speed = speed
        subs = {
            'start': sub_starts,
            'end': sub_ends,
            'text': sub_texts}

        save_subs_to_store(subs, youtube_id, item)

        log.info(
            """transcripts for Youtube ID {0} (speed {1})
            are downloaded from Youtube and
            saved.""".format(youtube_id, speed)
        )

        status_dict.update({speed: True})

    if not any(status_dict.itervalues()):
        log.error("Can't find any transcripts on the Youtube service.")
        return False

    # When we exit from the previous loop, `available_speed` and `subs`
    # are the transcripts data with the highest speed available on the
    # Youtube service. We use the highest speed as main speed for the
    # generation other transcripts, cause during calculation timestamps
    # for lower speeds we just use multiplication istead of division.

    # Generate transcripts for missed speeds.
    for speed, status in status_dict.iteritems():
        if not status:
            save_subs_to_store(
                generate_subs(speed, available_speed, subs),
                youtube_subs[speed],
                item)

            log.info(
                """transcripts for Youtube ID {0} (speed {1})
                are generated from Youtube ID {2} (speed {3}) and
                saved.""".format(
                youtube_subs[speed],
                speed,
                youtube_subs[available_speed],
                available_speed)
            )

    return True


def remove_subs_from_store(subs_id, item):
    """Remove from store, if transcripts content exists."""
    filename = 'subs_{0}.srt.sjson'.format(subs_id)
    content_location = StaticContent.compute_location(
        item.location.org, item.location.course, filename)
    try:
        content = contentstore().find(content_location)
        contentstore().delete(content.get_id())
    except NotFoundError:
        pass


def manage_video_transcripts(old_item, new_item):
    """Function for managing transcripts."""

    youtube_subs = {
        0.75: new_item.youtube_id_0_75,
        1: new_item.youtube_id_1_0,
        1.25: new_item.youtube_id_1_25,
        1.5: new_item.youtube_id_1_5
    }

    # If user has changed YT id, we remove transcripts.
    if new_item.youtube_id_1_0 != old_item.youtube_id_1_0:
        for youtube_id in youtube_subs.values():
            if youtube_id:
                remove_subs_from_store(youtube_id, new_item)

    # If user has changed HTML5 sources, we remove transcripts.
    old_src = set([src for src in old_item.html5_sources if src])
    new_src = set([src for src in new_item.html5_sources if src])
    if (old_src - new_src) and old_item.sub:
        remove_subs_from_store(old_item.sub, new_item)
        if new_item.sub == old_item.sub:
            new_item.sub = ''
            new_item.save()
            store = get_modulestore(Location(new_item.location))
            store.update_metadata(new_item.location, own_metadata(new_item))

    # Always download fresh transcripts from Youtube service if video
    # module has youtube type.
    if new_item.youtube_id_1_0:
        download_youtube_subs(youtube_subs, new_item)


def generate_subs_from_source(speed_subs, subs_type, subs_filedata, item):
    """Generate transcripts from source files (like SubRip format, etc.)
    and save them to assets for `item` module.
    We expect, that speed of source subs equal to 1

    :param speed_subs: dictionary {speed: sub_id, ...}
    :param subs_type: type of source subs: "srt", ...
    :param subs_filedata: content of source subs.
    :param item: module object.
    :returns: True, if all subs are generated and saved successfully.
    """
    html_parser = HTMLParser.HTMLParser()

    if subs_type != 'srt':
        log.error("We support only SubRip (*.srt) transcripts format.")
        return False

    srt_subs_obj = SubRipFile.from_string(subs_filedata)
    if not srt_subs_obj:
        log.error("Something wrong with SubRip transcripts file during parsing.")
        return False

    sub_starts = []
    sub_ends = []
    sub_texts = []

    for sub in srt_subs_obj:
        sub_starts.append(sub.start.ordinal)
        sub_ends.append(sub.end.ordinal)
        sub_texts.append(html_parser.unescape(sub.text.replace('\n', ' ')))

    subs = {
        'start': sub_starts,
        'end': sub_ends,
        'text': sub_texts}

    for speed, subs_id in speed_subs.iteritems():
        save_subs_to_store(
            generate_subs(speed, 1, subs),
            subs_id,
            item)

    return True


def generate_srt_from_sjson(sjson_subs, speed):
    """Generate transcripts with speed = 1.0 from sjson to SubRip (*.srt).

    :param sjson_subs: "sjson" subs.
    :param speed: speed of `sjson_subs`.
    :returns: "srt" subs.
    """
    if len(sjson_subs['start']) != len(sjson_subs['end']) or \
       len(sjson_subs['start']) != len(sjson_subs['text']):
        return None

    sjson_speed_1 = generate_subs(speed, 1, sjson_subs)
    output = StringIO.StringIO()

    for i in range(len(sjson_speed_1['start'])):
        item = SubRipItem(
            index=i,
            start=SubRipTime(milliseconds=sjson_speed_1['start'][i]),
            end=SubRipTime(milliseconds=sjson_speed_1['end'][i]),
            text=sjson_speed_1['text'][i])
        output.write(unicode(item))
        output.write('\n')

    output.seek(0)

    return output.read()
