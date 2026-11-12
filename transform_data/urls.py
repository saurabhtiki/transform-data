from django.urls import path

from . import views

app_name = "transform_data"
urlpatterns = [
    path("", views.home, name="home"),
    path("upload/", views.upload, name="upload"),
    path("table/remove/", views.remove_table, name="remove_table"),
    path("table/profile/", views.table_profile, name="table_profile"),
    path("start-over/", views.start_over, name="start_over"),
    path("step/pick/", views.step_picker, name="step_picker"),
    path("step/form/", views.step_form, name="step_form"),
    path("step/save/", views.step_save, name="step_save"),
    path("step/undo/", views.step_undo, name="step_undo"),
    path("steps/clear/", views.steps_clear, name="steps_clear"),
    path("formula/check/", views.formula_check, name="formula_check"),
    path("download/", views.download, name="download"),
    path("recipe/save/", views.recipe_save, name="recipe_save"),
    path("recipe/load/", views.recipe_load, name="recipe_load"),
    path("recipe/open/", views.recipe_open, name="recipe_open"),
]
