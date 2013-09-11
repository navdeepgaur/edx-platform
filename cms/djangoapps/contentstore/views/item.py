"""Views for items (modules)."""

import os
import logging
import json
from uuid import uuid4


from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.template.defaultfilters import slugify

from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.inheritance import own_metadata
from xmodule.modulestore.exceptions import ItemNotFoundError, InvalidLocationError
from xmodule.contentstore.django import contentstore
from xmodule.contentstore.content import StaticContent
from xmodule.exceptions import NotFoundError

from util.json_request import expect_json, JsonResponse
from ..utils import (get_modulestore, manage_video_transcripts,
                     return_ajax_status, generate_subs_from_source,
                     generate_srt_from_sjson, remove_subs_from_store,
                     save_subs_to_store, requests as rqsts,
                     download_youtube_subs)
from .access import has_access
from .requests import _xmodule_recurse
from xmodule.x_module import XModuleDescriptor

__all__ = ['save_item', 'create_item', 'delete_item', 'process_transcripts']

log = logging.getLogger(__name__)

# cdodge: these are categories which should not be parented, they are detached from the hierarchy
DETACHED_CATEGORIES = ['about', 'static_tab', 'course_info']


@login_required
@expect_json
def save_item(request):
    """
    Will carry a json payload with these possible fields
    :id (required): the id
    :data (optional): the new value for the data
    :metadata (optional): new values for the metadata fields.
        Any whose values are None will be deleted not set to None! Absent ones will be left alone
    :nullout (optional): which metadata fields to set to None
    """
    # The nullout is a bit of a temporary copout until we can make module_edit.coffee and the metadata editors a
    # little smarter and able to pass something more akin to {unset: [field, field]}
    item_location = request.POST['id']

    try:
        old_item = modulestore().get_item(item_location)
    except (ItemNotFoundError, InvalidLocationError):
        log.error("Can't find item by location.")
        return JsonResponse()

    # check permissions for this user within this course
    if not has_access(request.user, item_location):
        raise PermissionDenied()

    store = get_modulestore(Location(item_location))

    if request.POST.get('data') is not None:
        data = request.POST['data']
        store.update_item(item_location, data)

    # cdodge: note calling request.POST.get('children') will return None if children is an empty array
    # so it lead to a bug whereby the last component to be deleted in the UI was not actually
    # deleting the children object from the children collection
    if 'children' in request.POST and request.POST['children'] is not None:
        children = request.POST['children']
        store.update_children(item_location, children)

    # cdodge: also commit any metadata which might have been passed along
    if request.POST.get('nullout') is not None or request.POST.get('metadata') is not None:
        # the postback is not the complete metadata, as there's system metadata which is
        # not presented to the end-user for editing. So let's fetch the original and
        # 'apply' the submitted metadata, so we don't end up deleting system metadata
        existing_item = modulestore().get_item(item_location)
        for metadata_key in request.POST.get('nullout', []):
            setattr(existing_item, metadata_key, None)

        # update existing metadata with submitted metadata (which can be partial)
        # IMPORTANT NOTE: if the client passed 'null' (None) for a piece of metadata that means 'remove it'. If
        # the intent is to make it None, use the nullout field
        for metadata_key, value in request.POST.get('metadata', {}).items():
            field = existing_item.fields[metadata_key]

            if value is None:
                field.delete_from(existing_item)
            else:
                value = field.from_json(value)
                field.write_to(existing_item, value)
        # Save the data that we've just changed to the underlying
        # MongoKeyValueStore before we update the mongo datastore.
        existing_item.save()
        # commit to datastore
        store.update_metadata(item_location, own_metadata(existing_item))

    try:
        new_item = modulestore().get_item(item_location)
    except (ItemNotFoundError, InvalidLocationError):
        log.error("Can't find item by location.")
        return JsonResponse()

    if new_item.category == 'video':
        manage_video_transcripts(old_item, new_item)

    return JsonResponse()


@login_required
@expect_json
def create_item(request):
    """View for create items."""
    parent_location = Location(request.POST['parent_location'])
    category = request.POST['category']

    display_name = request.POST.get('display_name')

    if not has_access(request.user, parent_location):
        raise PermissionDenied()

    parent = get_modulestore(category).get_item(parent_location)
    dest_location = parent_location.replace(category=category, name=uuid4().hex)

    # get the metadata, display_name, and definition from the request
    metadata = {}
    data = None
    template_id = request.POST.get('boilerplate')
    if template_id is not None:
        clz = XModuleDescriptor.load_class(category)
        if clz is not None:
            template = clz.get_template(template_id)
            if template is not None:
                metadata = template.get('metadata', {})
                data = template.get('data')

    if display_name is not None:
        metadata['display_name'] = display_name

    get_modulestore(category).create_and_save_xmodule(
        dest_location,
        definition_data=data,
        metadata=metadata,
        system=parent.system,
    )

    if category not in DETACHED_CATEGORIES:
        get_modulestore(parent.location).update_children(parent_location, parent.children + [dest_location.url()])

    return JsonResponse({'id': dest_location.url()})


@login_required
@expect_json
def delete_item(request):
    """View for removing items."""
    item_location = request.POST['id']
    item_location = Location(item_location)

    # check permissions for this user within this course
    if not has_access(request.user, item_location):
        raise PermissionDenied()

    # optional parameter to delete all children (default False)
    delete_children = request.POST.get('delete_children', False)
    delete_all_versions = request.POST.get('delete_all_versions', False)

    store = get_modulestore(item_location)

    item = store.get_item(item_location)

    if delete_children:
        _xmodule_recurse(item, lambda i: store.delete_item(i.location, delete_all_versions))
    else:
        store.delete_item(item.location, delete_all_versions)

    # cdodge: we need to remove our parent's pointer to us so that it is no longer dangling
    if delete_all_versions:
        parent_locs = modulestore('direct').get_parent_locations(item_location, None)

        for parent_loc in parent_locs:
            parent = modulestore('direct').get_item(parent_loc)
            item_url = item_location.url()
            if item_url in parent.children:
                children = parent.children
                children.remove(item_url)
                parent.children = children
                modulestore('direct').update_children(parent.location, parent.children)

    return JsonResponse()


@return_ajax_status
def upload_transcripts(request):
    """Try to upload transcripts for current module."""

    # This view return True/False, cause we use `return_ajax_status`
    # view decorator.
    item_location = request.POST.get('id')
    if not item_location:
        log.error('POST data without "id" form data.')
        return False

    if 'file' not in request.FILES:
        log.error('POST data without "file" form data.')
        return False

    source_subs_filedata = request.FILES['file'].read()
    source_subs_filename = request.FILES['file'].name

    if '.' not in source_subs_filename:
        log.error("Undefined file extension.")
        return False

    basename = os.path.basename(source_subs_filename)
    source_subs_name = os.path.splitext(basename)[0]
    source_subs_ext = os.path.splitext(basename)[1][1:]

    try:
        item = modulestore().get_item(item_location)
    except (ItemNotFoundError, InvalidLocationError):
        log.error("Can't find item by location.")
        return False

    # Check permissions for this user within this course.
    if not has_access(request.user, item_location):
        raise PermissionDenied()

    if item.category != 'video':
        log.error('transcripts are supported only for "video" modules.')
        return False

    speed_subs = {
        0.75: item.youtube_id_0_75,
        1: item.youtube_id_1_0,
        1.25: item.youtube_id_1_25,
        1.5: item.youtube_id_1_5
    }

    if any(speed_subs.values()) and not any(item.html5_sources):
        log.error("Converting transcripts to youtube modules.")
        # do it here
        return False
    elif any(item.html5_sources):
        sub_attr = slugify(source_subs_name)

        # Generate only one subs for speed = 1.0
        status = generate_subs_from_source(
            {1: sub_attr},
            source_subs_ext,
            source_subs_filedata,
            item)

        if status:
            item.sub = sub_attr
            item.save()
            store = get_modulestore(Location(item_location))
            store.update_metadata(item_location, own_metadata(item))
    else:
        log.error('Empty video sources.')
        return False

    return status


def download_transcripts(request):
    """Try to download transcripts for current modules."""

    item_location = request.GET.get('id')
    if not item_location:
        log.error('GET data without "id" property.')
        raise Http404

    try:
        item = modulestore().get_item(item_location)
    except (ItemNotFoundError, InvalidLocationError):
        log.error("Can't find item by location.")
        raise Http404

    # Check permissions for this user within this course.
    if not has_access(request.user, item_location):
        raise PermissionDenied()

    if item.category != 'video':
        log.error('transcripts are supported only for video" modules.')
        raise Http404

    speed = 1
    speed_subs = {
        0.75: item.youtube_id_0_75,
        1: item.youtube_id_1_0,
        1.25: item.youtube_id_1_25,
        1.5: item.youtube_id_1_5
    }

    if any(speed_subs.values()):
        log.error("We don't support downloading subs for Youtube video modules.")
        raise Http404
    elif item.sub:
        filename = 'subs_{0}.srt.sjson'.format(item.sub)
        content_location = StaticContent.compute_location(
            item.location.org, item.location.course, filename)
        try:
            sjson_transcripts = contentstore().find(content_location)
        except NotFoundError:
            log.error("Can't find content in storage for non-youtube sub.")
            raise Http404

        srt_file_name = item.sub
    else:
        log.error('Blank "sub" field.')
        raise Http404

    str_subs = generate_srt_from_sjson(json.loads(sjson_transcripts.data), speed)
    if str_subs is None:
        raise Http404

    response = HttpResponse(str_subs, content_type='application/x-subrip')
    response['Content-Disposition'] = 'attachment; filename="{0}.srt"'.format(
        srt_file_name)

    return response


def check_transcripts(request):
    """Check transcripts availability for current modules.

    request.GET has key data, which can contain any of the following::
    [
        {u'type': u'youtube', u'video': u'OEoXaMPEzfM', u'mode': u'youtube'},
        {u'type': u'html5',    u'video': u'video1',             u'mode': u'mp4'}
        {u'type': u'html5',    u'video': u'video2',             u'mode': u'webm'}
    ]
    """
    transcripts_presence = {
        'html5_local': [],
        'youtube_local': False,
        'youtube_server': False,
        'status': 'Error'
    }
    data, item = validate_transcripts_data(request, transcripts_presence)

    transcripts_presence['status'] = 'Success'

    # preprocess data
    videos = {'youtube': '', 'html5': {}}
    for video_data in data.get('videos'):
        if video_data['type'] == 'youtube':
            videos['youtube'] = video_data['video']
        else:  # do not add same html5 videos
            if videos['html5'].get('video') != video_data['video']:
                videos['html5'][video_data['video']] = video_data['mode']

    # Check for youtube transcripts presence
    youtube_id = videos.get('youtube', None)
    if youtube_id:

        # youtube local
        filename = 'subs_{0}.srt.sjson'.format(youtube_id)
        content_location = StaticContent.compute_location(
            item.location.org, item.location.course, filename)
        try:
            contentstore().find(content_location)
            transcripts_presence['youtube_local'] = True
        except NotFoundError:
            log.debug("Can't find transcripts in storage for youtube id: {}".format(youtube_id))

        # youtube server
        youtube_response = rqsts.get(
            "http://video.google.com/timedtext",
            params={'lang': 'en', 'v': youtube_id}
        )
        if youtube_response.status_code == 200 and youtube_response.text:
            transcripts_presence['youtube_server'] = True

    # Check for html5 local transcripts presence
    for html5_id in videos:
        filename = 'subs_{0}.srt.sjson'.format(html5_id)
        content_location = StaticContent.compute_location(
            item.location.org, item.location.course, filename)
        try:
            contentstore().find(content_location)
            transcripts_presence['html5_local'].append(True)
        except NotFoundError:
            # change to log.message?
            log.debug("Can't find transcripts in storage for non-youtube video_id: {}".format(html5_id))
    return JsonResponse(transcripts_presence)


def choose_transcripts(request):
    """
    Replaces html5 subtitles, presented for both html5 sources,
    with chosen one.

    1. Remove rejeceted html5 subtitles
    2. Update sub attribute with correct html5_id

    Do nothing with youtube id's.
    """
    response = {'status': 'Error'}
    data, item = validate_transcripts_data(request, response)

    # preprocess data
    videos = {'html5': {}}
    for video_data in data.get('videos'):
        videos['html5'][video_data['video']] = video_data['mode']

    html5_id = data.get('html5_id')

    # find rejected html5_id and remove appropriate subs from store
    html5_id_to_remove = [x for x in videos['html5'] if x != html5_id]
    remove_subs_from_store(html5_id_to_remove, item)

    # update sub value
    if item.sub != slugify(html5_id):
        item.sub = slugify(html5_id)
        item.save()
    response['status'] = 'Success'
    return JsonResponse(response)


def replace_transcripts(request):
    """
    Replaces all transcripts with youtube ones.
    """
    response = {'status': 'Error'}
    data, item = validate_transcripts_data(request, response)

    # preprocess data
    youtube_id = None
    for video_data in data.get('videos'):
        if video_data['type'] == 'youtube':
            youtube_id = video_data['type']
            break

    if not youtube_id:
        return JsonResponse(response)

    download_youtube_subs(youtube_id, item)
    item.sub = slugify(youtube_id)
    item.save()
    response['status'] = 'Success'
    return JsonResponse(response)


def validate_transcripts_data(request, response):
    """
    Validates, that request containts all proper data for transcripts processing.

    Returns parsed data from request and video item from store.
    """

    data = json.loads(request.GET.get('data', '[]'))
    if not data:
        log.error('Incoming video data is empty.')
        return JsonResponse(response)

    item_location = data.get('id')
    try:
        item = modulestore().get_item(item_location)
    except (ItemNotFoundError, InvalidLocationError):
        log.error("Can't find item by location.")
        return JsonResponse(response)

    # Check permissions for this user within this course.
    if not has_access(request.user, item_location):
        raise PermissionDenied()

    if item.category != 'video':
        log.error('transcripts are supported only for "video" modules.')
        return JsonResponse(response)

    return data, item


@login_required
def process_transcripts(request, action):
    """
    Dispatcher for trascripts actions.
    """
    allowed_actions = {
        'upload': upload_transcripts,
        'donwload': download_transcripts,
        'check': check_transcripts,
        'choose': choose_transcripts,
        'replace': replace_transcripts
    }
    return allowed_actions.get(action, lambda x: JsonResponse())(request)
