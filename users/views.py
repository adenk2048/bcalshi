import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt


def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            # New accounts are inactive until the superaccount approves them
            # (keeps the platform semi-private). Inactive users cannot log in
            # through any path, so we do NOT auto-login here.
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            return render(request, "registration/signup.html", {"submitted": True})
    else:
        form = UserCreationForm()

    return render(request, "registration/signup.html", {"form": form})


@csrf_exempt
def register(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    data = json.loads(request.body)
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return JsonResponse({"error": "missing fields"}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "user exists"}, status=400)

    # Inactive until approved — same rule as the signup page.
    User.objects.create_user(username=username, password=password, is_active=False)
    return JsonResponse({"success": True, "pending_approval": True})


@csrf_exempt
def login_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    data = json.loads(request.body)
    # authenticate() returns None for inactive users, so unapproved accounts
    # are rejected here automatically.
    user = authenticate(
        request,
        username=data.get("username"),
        password=data.get("password"),
    )
    if user is None:
        return JsonResponse({"error": "invalid credentials or account not yet approved"}, status=400)

    login(request, user)
    return JsonResponse({"success": True, "username": user.username})


def logout_view(request):
    logout(request)
    return JsonResponse({"success": True})


def me(request):
    if request.user.is_authenticated:
        return JsonResponse({
            "logged_in": True,
            "username": request.user.username,
        })
    return JsonResponse({"logged_in": False})


# ---------------------------------------------------------------- account approval

def _staff_guard(request):
    """JSON guard for superaccount-only POST endpoints."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)
    if not request.user.is_staff:
        return JsonResponse({"error": "superaccount required"}, status=403)
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    return None


def approve_user(request, user_id):
    guard = _staff_guard(request)
    if guard:
        return guard

    user = User.objects.filter(id=user_id).first()
    if user is None:
        return JsonResponse({"error": "user not found"}, status=404)
    if user.is_staff:
        return JsonResponse({"error": "cannot modify a staff account"}, status=400)

    user.is_active = True
    user.save(update_fields=["is_active"])
    return JsonResponse({"success": True, "username": user.username, "status": "approved"})


def reject_user(request, user_id):
    guard = _staff_guard(request)
    if guard:
        return guard

    user = User.objects.filter(id=user_id).first()
    if user is None:
        return JsonResponse({"error": "user not found"}, status=404)
    if user.is_staff:
        return JsonResponse({"error": "cannot delete a staff account"}, status=400)
    # Only ever delete accounts that are still pending — never an approved member.
    if user.is_active:
        return JsonResponse({"error": "user is already approved; deactivate in admin instead"}, status=400)

    username = user.username
    user.delete()
    return JsonResponse({"success": True, "username": username, "status": "rejected"})
