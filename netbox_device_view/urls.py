from django.urls import path
from . import models, views
from netbox.views.generic import ObjectChangeLogView

urlpatterns = (
    path("device-view/", views.DeviceViewListView.as_view(), name="deviceview_list"),
    path("device-view/add/", views.DeviceViewEditView.as_view(), name="deviceview_add"),
    path(
        "device-view/device-type/<int:pk>/layout-data/",
        views.DeviceTypeLayoutDataView.as_view(),
        name="devicetype_layout_data",
    ),
    path(
        "device-view/device-type/<int:pk>/devices/",
        views.DeviceTypeDevicesView.as_view(),
        name="devicetype_devices",
    ),
    path(
        "device-view/parse-css/",
        views.DeviceViewParseCssView.as_view(),
        name="deviceview_parse_css",
    ),
    path(
        "device-view/preview/",
        views.DeviceViewPreviewView.as_view(),
        name="deviceview_preview",
    ),
    path(
        "device-view/import/",
        views.DeviceViewBulkImportView.as_view(),
        name="deviceview_import",
    ),
    path(
        "device-view/delete/",
        views.DeviceViewBulkDeleteView.as_view(),
        name="deviceview_bulk_delete",
    ),
    path("device-view/<int:pk>/", views.DeviceViewView.as_view(), name="deviceview"),
    path(
        "device-view/<int:pk>/edit/",
        views.DeviceViewEditView.as_view(),
        name="deviceview_edit",
    ),
    path(
        "device-view/<int:pk>/delete/",
        views.DeviceViewDeleteView.as_view(),
        name="deviceview_delete",
    ),
    path(
        "device-view/<int:pk>/changelog/",
        ObjectChangeLogView.as_view(),
        name="deviceview_changelog",
        kwargs={"model": models.DeviceView},
    ),
)
