# Generated by Django 3.0.7 on 2020-06-29 19:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_auto_20200531_2058"),
    ]

    operations = [
        migrations.AddField(
            model_name="coresettings",
            name="mesh_token",
            field=models.CharField(
                blank=True, default="changeme", max_length=255, null=True
            ),
        ),
    ]