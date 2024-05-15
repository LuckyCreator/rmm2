import json
import os
from unittest.mock import patch

from django.conf import settings
from django.utils import timezone as djangotime
from model_bakery import baker

from tacticalrmm.test import TacticalTestCase


class TestAPIv3(TacticalTestCase):
    def setUp(self):
        self.authenticate()
        self.setup_coresettings()
        self.agent = baker.make_recipe("agents.agent")

    def test_get_checks(self):
        url = f"/api/v3/{self.agent.agent_id}/checkrunner/"

        # add a check
        check1 = baker.make_recipe("checks.ping_check", agent=self.agent)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["check_interval"], self.agent.check_interval)  # type: ignore
        self.assertEqual(len(r.data["checks"]), 1)  # type: ignore

        # override check run interval
        check2 = baker.make_recipe(
            "checks.ping_check", agent=self.agent, run_interval=20
        )

        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["check_interval"], 20)  # type: ignore
        self.assertEqual(len(r.data["checks"]), 2)  # type: ignore

        # Set last_run on both checks and should return an empty list
        check1.last_run = djangotime.now()
        check1.save()
        check2.last_run = djangotime.now()
        check2.save()

        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["check_interval"], 20)  # type: ignore
        self.assertFalse(r.data["checks"])  # type: ignore

        # set last_run greater than interval
        check1.last_run = djangotime.now() - djangotime.timedelta(seconds=200)
        check1.save()
        check2.last_run = djangotime.now() - djangotime.timedelta(seconds=200)
        check2.save()

        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["check_interval"], 20)  # type: ignore
        self.assertEquals(len(r.data["checks"]), 2)  # type: ignore

        url = "/api/v3/Maj34ACb324j234asdj2n34kASDjh34-DESKTOPTEST123/checkrunner/"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        self.check_not_authenticated("get", url)

    def test_sysinfo(self):
        # TODO replace this with golang wmi sample data

        url = "/api/v3/sysinfo/"
        with open(
            os.path.join(
                settings.BASE_DIR, "tacticalrmm/test_data/wmi_python_agent.json"
            )
        ) as f:
            wmi_py = json.load(f)

        payload = {"agent_id": self.agent.agent_id, "sysinfo": wmi_py}

        r = self.client.patch(url, payload, format="json")
        self.assertEqual(r.status_code, 200)

        self.check_not_authenticated("patch", url)

    def test_checkrunner_interval(self):
        url = f"/api/v3/{self.agent.agent_id}/checkinterval/"
        r = self.client.get(url, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(),
            {"agent": self.agent.pk, "check_interval": self.agent.check_interval},
        )

        # add check to agent with check interval set
        check = baker.make_recipe(
            "checks.ping_check", agent=self.agent, run_interval=30
        )

        r = self.client.get(url, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(),
            {"agent": self.agent.pk, "check_interval": 30},
        )

        # minimum check run interval is 15 seconds
        check = baker.make_recipe("checks.ping_check", agent=self.agent, run_interval=5)

        r = self.client.get(url, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(),
            {"agent": self.agent.pk, "check_interval": 15},
        )

    def test_run_checks(self):
        # force run all checks regardless of interval
        agent = baker.make_recipe("agents.online_agent")
        baker.make_recipe("checks.ping_check", agent=agent)
        baker.make_recipe("checks.diskspace_check", agent=agent)
        baker.make_recipe("checks.cpuload_check", agent=agent)
        baker.make_recipe("checks.memory_check", agent=agent)
        baker.make_recipe("checks.eventlog_check", agent=agent)
        for _ in range(10):
            baker.make_recipe("checks.script_check", agent=agent)

        url = f"/api/v3/{agent.agent_id}/runchecks/"
        r = self.client.get(url)
        self.assertEqual(r.json()["agent"], agent.pk)
        self.assertIsInstance(r.json()["check_interval"], int)
        self.assertEqual(len(r.json()["checks"]), 15)

    def test_checkin_patch(self):
        from logs.models import PendingAction

        url = "/api/v3/checkin/"
        agent_updated = baker.make_recipe("agents.agent", version="1.3.0")
        PendingAction.objects.create(
            agent=agent_updated,
            action_type="agentupdate",
            details={
                "url": agent_updated.winagent_dl,
                "version": agent_updated.version,
                "inno": agent_updated.win_inno_exe,
            },
        )
        action = agent_updated.pendingactions.filter(action_type="agentupdate").first()
        self.assertEqual(action.status, "pending")

        # test agent failed to update and still on same version
        payload = {
            "func": "hello",
            "agent_id": agent_updated.agent_id,
            "version": "1.3.0",
        }
        r = self.client.patch(url, payload, format="json")
        self.assertEqual(r.status_code, 200)
        action = agent_updated.pendingactions.filter(action_type="agentupdate").first()
        self.assertEqual(action.status, "pending")

        # test agent successful update
        payload["version"] = settings.LATEST_AGENT_VER
        r = self.client.patch(url, payload, format="json")
        self.assertEqual(r.status_code, 200)
        action = agent_updated.pendingactions.filter(action_type="agentupdate").first()
        self.assertEqual(action.status, "completed")
        action.delete()

    @patch("apiv3.views.reload_nats")
    def test_agent_recovery(self, reload_nats):
        reload_nats.return_value = "ok"
        r = self.client.get("/api/v3/34jahsdkjasncASDjhg2b3j4r/recover/")
        self.assertEqual(r.status_code, 404)

        agent = baker.make_recipe("agents.online_agent")
        url = f"/api/v3/{agent.agent_id}/recovery/"

        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"mode": "pass", "shellcmd": ""})
        reload_nats.assert_not_called()

        baker.make("agents.RecoveryAction", agent=agent, mode="mesh")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"mode": "mesh", "shellcmd": ""})
        reload_nats.assert_not_called()

        baker.make(
            "agents.RecoveryAction",
            agent=agent,
            mode="command",
            command="shutdown /r /t 5 /f",
        )
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(), {"mode": "command", "shellcmd": "shutdown /r /t 5 /f"}
        )
        reload_nats.assert_not_called()

        baker.make("agents.RecoveryAction", agent=agent, mode="rpc")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"mode": "rpc", "shellcmd": ""})
        reload_nats.assert_called_once()
