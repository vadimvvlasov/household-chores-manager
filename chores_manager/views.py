from django.http import HttpResponse


def home(request):
    return HttpResponse("Household Chores Manager")
