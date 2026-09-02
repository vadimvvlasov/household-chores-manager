from django.urls import path

from . import views

urlpatterns = [
    path("<int:instance_id>/check/", views.check_instance, name="check_instance"),
    path("<int:instance_id>/uncheck/", views.uncheck_instance, name="uncheck_instance"),
    path("<int:instance_id>/log-time/", views.log_time, name="log_time"),
    path("<int:instance_id>/swap/", views.swap, name="swap"),
]
