from django.apps import AppConfig


class TransformDataConfig(AppConfig):
    name = "transform_data"
    verbose_name = "Transform Data"

    def ready(self):
        from django.contrib.auth.signals import user_logged_out

        from .state import registry

        # A user who logs out leaves no data behind in memory.
        user_logged_out.connect(registry.forget_on_logout, dispatch_uid="transform_data_logout")
