import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt


def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # auto login
            return redirect("/portfolio/")
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

    User.objects.create_user(username=username, password=password)
    return JsonResponse({"success": True})


@csrf_exempt
def login_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    data = json.loads(request.body)
    user = authenticate(
        request,
        username=data.get("username"),
        password=data.get("password"),
    )
    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=400)

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
