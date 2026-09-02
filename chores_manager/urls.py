"""
URL configuration for chores_manager project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from chores import views as chores_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("people.urls")),
    path("", chores_views.dashboard, name="home"),
    path("calendar/", chores_views.calendar_view, name="calendar"),
    path("chores/", include("chores.urls")),
    path("assignments/new/", chores_views.assignment_edit, name="assignment_new"),
    path(
        "assignments/<int:template_id>/edit/",
        chores_views.assignment_edit,
        name="assignment_edit",
    ),
    path("people/<int:person_id>/budget/", chores_views.budget_edit, name="budget_edit"),
    path("approvals/", chores_views.approvals_list, name="approvals"),
    path(
        "approvals/assignment/<int:pk>/approve/",
        chores_views.approve_assignment_change,
        name="approve_assignment_change",
    ),
    path(
        "approvals/assignment/<int:pk>/reject/",
        chores_views.reject_assignment_change,
        name="reject_assignment_change",
    ),
    path(
        "approvals/budget/<int:pk>/approve/",
        chores_views.approve_budget_change,
        name="approve_budget_change",
    ),
    path(
        "approvals/budget/<int:pk>/reject/",
        chores_views.reject_budget_change,
        name="reject_budget_change",
    ),
]
