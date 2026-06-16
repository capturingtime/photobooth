from django.shortcuts import render


def index(request):
    return render(request, "index.html")


def last(request):
    return render(request, "last.html")


def attract(request):
    return render(request, "attract.html")


def last_capture(request):
    return render(request, "last_capture.html")


def series_capture(request):
    return render(request, "series_capture.html")


def series_final(request):
    return render(request, "series_final.html")


def single_final(request):
    return render(request, "single_final.html")


def unavailable(request):
    return render(request, "unavailable.html")
