from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from ops.books import audit
from ops.models import Employee


class Command(BaseCommand):
    help = "Siapkan undangan admin pertama untuk database ini."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **opts):
        if Employee.objects.exists():
            raise CommandError("Bootstrap hanya berlaku pada database pegawai kosong.")
        email = opts["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Email tidak valid.") from exc
        u = Employee.objects.create_user(
            username=email,
            email=email,
            first_name="Administrator",
            role="Admin",
            password=None,
        )
        audit(u, "Undangan admin awal", email)
        self.stdout.write("Undangan admin tersimpan.")
