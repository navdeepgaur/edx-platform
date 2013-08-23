"""


"""
import json
import logging

from mitxmako.shortcuts import render_to_response

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic.base import View

from course_modes.models import CourseMode
from student.models import CourseEnrollment
from student.views import course_from_id
from shoppingcart.models import Order, CertificateItem
from shoppingcart.processors.CyberSource import (
    get_signed_purchase_params, get_purchase_endpoint
)
from verify_student.models import SoftwareSecurePhotoVerification

log = logging.getLogger(__name__)

class VerifyView(View):

    def get(self, request):
        """
        """
        # If the user has already been verified within the given time period,
        # redirect straight to the payment -- no need to verify again.
        if SoftwareSecurePhotoVerification.user_has_valid_or_pending(request.user):
            progress_state = "payment"
        else:
            # If they haven't completed a verification attempt, we have to
            # restart with a new one. We can't reuse an older one because we
            # won't be able to show them their encrypted photo_id -- it's easier
            # bookkeeping-wise just to start over.
            progress_state = "start"

        course_id = request.GET['course_id']
        context = {
            "progress_state" : progress_state,
            "user_full_name" : request.user.profile.name,
            "course_id" : course_id,
            "course_name" : course_from_id(course_id).display_name,
            "purchase_endpoint" : get_purchase_endpoint(),
        }

        return render_to_response('verify_student/photo_verification.html', context)


def create_order(request):
    attempt = SoftwareSecurePhotoVerification(user=request.user)
    attempt.status = "pending"
    attempt.save()

    course_id = request.POST['course_id']
    log.critical(course_id)

    # I know, we should check this is valid. All kinds of stuff missing here
    # enrollment = CourseEnrollment.create_enrollment(request.user, course_id)
    cart = Order.get_cart_for_user(request.user)
    CertificateItem.add_to_order(cart, course_id, 30, 'verified')

    params = get_signed_purchase_params(cart)

    return HttpResponse(json.dumps(params), content_type="text/json")


def show_requirements(request):
    """This might just be a plain template without a view."""
    context = { "course_id" : "edX/Certs101/2013_Test" }
    return render_to_response("verify_student/show_requirements.html", context)

def face_upload(request):
    context = { "course_id" : "edX/Certs101/2013_Test" }
    return render_to_response("verify_student/face_upload.html", context)

def photo_id_upload(request):
    context = { "course_id" : "edX/Certs101/2013_Test" }
    return render_to_response("verify_student/photo_id_upload.html", context)

def final_verification(request):
    context = { "course_id" : "edX/Certs101/2013_Test" }
    return render_to_response("verify_student/final_verification.html", context)

def show_verification_page(request):
    pass


def enroll(user, course_id, mode_slug):
    """
    Enroll the user in a course for a certain mode.

    This is the view you send folks to when they click on the enroll button.
    This does NOT cover changing enrollment modes -- it's intended for new
    enrollments only, and will just redirect to the dashboard if it detects
    that an enrollment already exists.
    """
    # If the user is already enrolled, jump to the dashboard. Yeah, we could
    # do upgrades here, but this method is complicated enough.
    if CourseEnrollment.is_enrolled(user, course_id):
        return HttpResponseRedirect(reverse('dashboard'))

    available_modes = CourseModes.modes_for_course(course_id)

    # If they haven't chosen a mode...
    if not mode_slug:
        # Does this course support multiple modes of Enrollment? If so, redirect
        # to a page that lets them choose which mode they want.
        if len(available_modes) > 1:
            return HttpResponseRedirect(
                reverse('choose_enroll_mode', course_id=course_id)
            )
        # Otherwise, we use the only mode that's supported...
        else:
            mode_slug = available_modes[0].slug

    # If the mode is one of the simple, non-payment ones, do the enrollment and
    # send them to their dashboard.
    if mode_slug in ("honor", "audit"):
        CourseEnrollment.enroll(user, course_id, mode=mode_slug)
        return HttpResponseRedirect(reverse('dashboard'))

    if mode_slug == "verify":
        if SoftwareSecureVerification.has_submitted_recent_request(user):
            # Capture payment info
            # Create an order
            # Create a VerifiedCertificate order item
            return HttpResponse.Redirect(reverse('payment'))


    # There's always at least one mode available (default is "honor"). If they
    # haven't specified a mode, we just assume it's
    if not mode:
        mode = available_modes[0]

    elif len(available_modes) == 1:
        if mode != available_modes[0]:
            raise Exception()

        mode = available_modes[0]

    if mode == "honor":
        CourseEnrollment.enroll(user, course_id)
        return HttpResponseRedirect(reverse('dashboard'))
