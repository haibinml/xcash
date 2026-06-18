from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from currencies.views import MetadataView
from deposits.viewsets import DepositViewSet
from invoices.viewsets import InvoiceViewSet

router = (
    DefaultRouter(trailing_slash=False)
    if settings.DEBUG
    else SimpleRouter(trailing_slash=False)
)

router.register("invoice", InvoiceViewSet)
router.register("deposit", DepositViewSet, basename="deposit")

app_name = "api_v1"
urlpatterns = [
    path("metadata", MetadataView.as_view(), name="metadata"),
    *router.urls,
]
