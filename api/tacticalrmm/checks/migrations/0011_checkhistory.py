# Generated by Django 3.1.4 on 2021-01-09 21:36

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checks", "0010_auto_20200922_1344"),
    ]

    operations = [
        migrations.CreateModel(
            name="CheckHistory",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("x", models.DateTimeField()),
                ("y", models.PositiveIntegerField()),
                ("results", models.JSONField(blank=True, null=True)),
                (
                    "check_history",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="check_history",
                        to="checks.check",
                    ),
                ),
            ],
        ),
    ]
