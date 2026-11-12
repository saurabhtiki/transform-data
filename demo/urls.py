from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/transform/", permanent=False)),
    path("transform/", include("transform_data.urls")),
]
