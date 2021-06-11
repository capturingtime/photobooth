from django.shortcuts import render


# Create your views here.
def index(request):
    # return HttpResponse("Hello, World!")
    return render(request, 'index.html')


def last(request):
    return render(request, 'last.html')
