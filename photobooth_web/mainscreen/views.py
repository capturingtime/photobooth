from django.shortcuts import render


def _series_context(request):
    """Extract series-banner context from the request query string.

    ``booth_main`` appends ``?mode=...&total=...&shot=...`` via
    ``PhotoBooth.display_url_with_context`` so templates can render the
    "Shot X of N" / "Next shot: X of N" overlays without any shared
    in-memory state. ``shot`` and ``total`` are coerced to int when
    present so template arithmetic / comparisons stay sane.
    """
    mode = request.GET.get("mode")
    total = request.GET.get("total")
    shot = request.GET.get("shot")
    try:
        total_int = int(total) if total is not None else None
    except (TypeError, ValueError):
        total_int = None
    try:
        shot_int = int(shot) if shot is not None else None
    except (TypeError, ValueError):
        shot_int = None
    return {"mode": mode, "total": total_int, "shot": shot_int}


def index(request):
    return render(request, "index.html")


def attract(request):
    return render(request, "attract.html", _series_context(request))


def last_capture(request):
    return render(request, "last_capture.html", _series_context(request))


def series_capture(request):
    return render(request, "series_capture.html", _series_context(request))


def series_final(request):
    return render(request, "series_final.html")


def single_final(request):
    return render(request, "single_final.html")


def unavailable(request):
    return render(request, "unavailable.html")
