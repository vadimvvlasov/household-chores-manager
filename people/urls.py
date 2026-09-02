from django.contrib.auth.views import LoginView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", LoginView.as_view(template_name="people/login.html"), name="login"),
    path("profile/", views.profile_picker, name="profile_picker"),
    path("profile/select/", views.select_person, name="select_person"),
    path("logout/", views.ActivePersonLogoutView.as_view(), name="logout"),
]
