import datetime as dt
import random
import string

import pytz
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.fields import DateTimeField
from loguru import logger

from alerts.models import SEVERITY_CHOICES
from logs.models import BaseAuditModel
from tacticalrmm.utils import bitdays_to_string

logger.configure(**settings.LOG_CONFIG)

RUN_TIME_DAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]

TASK_TYPE_CHOICES = [
    ("scheduled", "Scheduled"),
    ("checkfailure", "On Check Failure"),
    ("manual", "Manual"),
    ("runonce", "Run Once"),
]

SYNC_STATUS_CHOICES = [
    ("synced", "Synced With Agent"),
    ("notsynced", "Waiting On Agent Checkin"),
    ("pendingdeletion", "Pending Deletion on Agent"),
]

TASK_STATUS_CHOICES = [
    ("passing", "Passing"),
    ("failing", "Failing"),
    ("pending", "Pending"),
]


class AutomatedTask(BaseAuditModel):
    agent = models.ForeignKey(
        "agents.Agent",
        related_name="autotasks",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    policy = models.ForeignKey(
        "automation.Policy",
        related_name="autotasks",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    script = models.ForeignKey(
        "scripts.Script",
        null=True,
        blank=True,
        related_name="autoscript",
        on_delete=models.CASCADE,
    )
    script_args = ArrayField(
        models.CharField(max_length=255, null=True, blank=True),
        null=True,
        blank=True,
        default=list,
    )
    assigned_check = models.ForeignKey(
        "checks.Check",
        null=True,
        blank=True,
        related_name="assignedtask",
        on_delete=models.SET_NULL,
    )
    name = models.CharField(max_length=255)
    run_time_bit_weekdays = models.IntegerField(null=True, blank=True)
    # run_time_days is deprecated, use bit weekdays
    run_time_days = ArrayField(
        models.IntegerField(choices=RUN_TIME_DAY_CHOICES, null=True, blank=True),
        null=True,
        blank=True,
        default=list,
    )
    run_time_minute = models.CharField(max_length=5, null=True, blank=True)
    task_type = models.CharField(
        max_length=100, choices=TASK_TYPE_CHOICES, default="manual"
    )
    run_time_date = DateTimeField(null=True, blank=True)
    remove_if_not_scheduled = models.BooleanField(default=False)
    run_asap_after_missed = models.BooleanField(default=False)  # added in agent v1.4.7
    managed_by_policy = models.BooleanField(default=False)
    parent_task = models.PositiveIntegerField(null=True, blank=True)
    win_task_name = models.CharField(max_length=255, null=True, blank=True)
    timeout = models.PositiveIntegerField(default=120)
    retcode = models.IntegerField(null=True, blank=True)
    stdout = models.TextField(null=True, blank=True)
    stderr = models.TextField(null=True, blank=True)
    execution_time = models.CharField(max_length=100, default="0.0000")
    last_run = models.DateTimeField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    status = models.CharField(
        max_length=30, choices=TASK_STATUS_CHOICES, default="pending"
    )
    sync_status = models.CharField(
        max_length=100, choices=SYNC_STATUS_CHOICES, default="notsynced"
    )
    alert_severity = models.CharField(
        max_length=30, choices=SEVERITY_CHOICES, default="info"
    )
    email_alert = models.BooleanField(default=False)
    text_alert = models.BooleanField(default=False)
    dashboard_alert = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    @property
    def schedule(self):
        if self.task_type == "manual":
            return "Manual"
        elif self.task_type == "checkfailure":
            return "Every time check fails"
        elif self.task_type == "runonce":
            return f'Run once on {self.run_time_date.strftime("%m/%d/%Y %I:%M%p")}'
        elif self.task_type == "scheduled":
            run_time_nice = dt.datetime.strptime(
                self.run_time_minute, "%H:%M"
            ).strftime("%I:%M %p")

            days = bitdays_to_string(self.run_time_bit_weekdays)
            return f"{days} at {run_time_nice}"

    @property
    def last_run_as_timezone(self):
        if self.last_run is not None and self.agent is not None:
            return self.last_run.astimezone(
                pytz.timezone(self.agent.timezone)
            ).strftime("%b-%d-%Y - %H:%M")

        return self.last_run

    @staticmethod
    def generate_task_name():
        chars = string.ascii_letters
        return "TacticalRMM_" + "".join(random.choice(chars) for i in range(35))

    @staticmethod
    def serialize(task):
        # serializes the task and returns json
        from .serializers import TaskSerializer

        return TaskSerializer(task).data

    def create_policy_task(self, agent=None, policy=None):
        from .tasks import create_win_task_schedule

        # if policy is present, then this task is being copied to another policy
        # if agent is present, then this task is being created on an agent from a policy
        # exit if neither are set or if both are set
        if not agent and not policy or agent and policy:
            return

        assigned_check = None

        # get correct assigned check to task if set
        if agent and self.assigned_check:
            # check if there is a matching check on the agent
            if agent.agentchecks.filter(parent_check=self.assigned_check.pk).exists():
                assigned_check = agent.agentchecks.filter(
                    parent_check=self.assigned_check.pk
                ).first()
            # check was overriden by agent and we need to use that agents check
            else:
                if agent.agentchecks.filter(
                    check_type=self.assigned_check.check_type, overriden_by_policy=True
                ).exists():
                    assigned_check = agent.agentchecks.filter(
                        check_type=self.assigned_check.check_type,
                        overriden_by_policy=True,
                    ).first()
        elif policy and self.assigned_check:
            if policy.policychecks.filter(name=self.assigned_check.name).exists():
                assigned_check = policy.policychecks.filter(
                    name=self.assigned_check.name
                ).first()
            else:
                assigned_check = policy.policychecks.filter(
                    check_type=self.assigned_check.check_type
                ).first()

        task = AutomatedTask.objects.create(
            agent=agent,
            policy=policy,
            managed_by_policy=bool(agent),
            parent_task=(self.pk if agent else None),
            alert_severity=self.alert_severity,
            email_alert=self.email_alert,
            text_alert=self.text_alert,
            dashboard_alert=self.dashboard_alert,
            script=self.script,
            script_args=self.script_args,
            assigned_check=assigned_check,
            name=self.name,
            run_time_days=self.run_time_days,
            run_time_minute=self.run_time_minute,
            run_time_bit_weekdays=self.run_time_bit_weekdays,
            run_time_date=self.run_time_date,
            task_type=self.task_type,
            win_task_name=self.win_task_name,
            timeout=self.timeout,
            enabled=self.enabled,
            remove_if_not_scheduled=self.remove_if_not_scheduled,
            run_asap_after_missed=self.run_asap_after_missed,
        )

        create_win_task_schedule.delay(task.pk)

    def should_create_alert(self, alert_template=None):
        return (
            self.dashboard_alert
            or self.email_alert
            or self.text_alert
            or (
                alert_template
                and (
                    alert_template.task_always_alert
                    or alert_template.task_always_email
                    or alert_template.task_always_text
                )
            )
        )

    def send_email(self):
        from core.models import CoreSettings

        CORE = CoreSettings.objects.first()

        if self.agent:
            subject = f"{self.agent.client.name}, {self.agent.site.name}, {self} Failed"
        else:
            subject = f"{self} Failed"

        body = (
            subject
            + f" - Return code: {self.retcode}\nStdout:{self.stdout}\nStderr: {self.stderr}"
        )

        CORE.send_mail(subject, body, self.agent.alert_template)

    def send_sms(self):

        from core.models import CoreSettings

        CORE = CoreSettings.objects.first()

        if self.agent:
            subject = f"{self.agent.client.name}, {self.agent.site.name}, {self} Failed"
        else:
            subject = f"{self} Failed"

        body = (
            subject
            + f" - Return code: {self.retcode}\nStdout:{self.stdout}\nStderr: {self.stderr}"
        )

        CORE.send_sms(body, alert_template=self.agent.alert_template)

    def send_resolved_email(self):
        from core.models import CoreSettings

        CORE = CoreSettings.objects.first()
        subject = f"{self.agent.client.name}, {self.agent.site.name}, {self} Resolved"
        body = (
            subject
            + f" - Return code: {self.retcode}\nStdout:{self.stdout}\nStderr: {self.stderr}"
        )

        CORE.send_mail(subject, body, alert_template=self.agent.alert_template)

    def send_resolved_sms(self):
        from core.models import CoreSettings

        CORE = CoreSettings.objects.first()
        subject = f"{self.agent.client.name}, {self.agent.site.name}, {self} Resolved"
        body = (
            subject
            + f" - Return code: {self.retcode}\nStdout:{self.stdout}\nStderr: {self.stderr}"
        )
        CORE.send_sms(body, alert_template=self.agent.alert_template)
