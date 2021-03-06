from __future__ import absolute_import

import six
import json
import requests
import pytz

from exam import fixture
from freezegun import freeze_time

from sentry.api.serializers import serialize
from sentry.incidents.logic import create_alert_rule
from sentry.incidents.models import AlertRule
from sentry.snuba.models import QueryAggregations
from sentry.testutils.helpers.datetime import before_now
from sentry.testutils import TestCase, APITestCase
from tests.sentry.api.serializers.test_alert_rule import BaseAlertRuleSerializerTest


class AlertRuleListEndpointTest(APITestCase):
    endpoint = "sentry-api-0-project-alert-rules"

    @fixture
    def organization(self):
        return self.create_organization()

    @fixture
    def project(self):
        return self.create_project(organization=self.organization)

    @fixture
    def user(self):
        return self.create_user()

    def test_empty(self):
        self.create_team(organization=self.organization, members=[self.user])

    def test_simple(self):
        self.create_team(organization=self.organization, members=[self.user])
        alert_rule = create_alert_rule(
            self.organization,
            [self.project],
            "hello",
            "level:error",
            QueryAggregations.TOTAL,
            10,
            1,
        )

        self.login_as(self.user)
        with self.feature("organizations:incidents"):
            resp = self.get_valid_response(self.organization.slug, self.project.slug)

        assert resp.data == serialize([alert_rule])

    def test_no_feature(self):
        self.create_team(organization=self.organization, members=[self.user])
        self.login_as(self.user)
        resp = self.get_response(self.organization.slug, self.project.slug)
        assert resp.status_code == 404


@freeze_time()
class AlertRuleCreateEndpointTest(APITestCase):
    endpoint = "sentry-api-0-project-alert-rules"
    method = "post"

    @fixture
    def organization(self):
        return self.create_organization()

    @fixture
    def project(self):
        return self.create_project(organization=self.organization)

    @fixture
    def user(self):
        return self.create_user()

    def test_simple(self):
        self.create_member(
            user=self.user, organization=self.organization, role="owner", teams=[self.team]
        )
        self.login_as(self.user)
        name = "an alert"
        query = "hi"
        aggregation = 0
        time_window = 10
        with self.feature("organizations:incidents"):
            resp = self.get_valid_response(
                self.organization.slug,
                self.project.slug,
                name=name,
                query=query,
                aggregation=aggregation,
                timeWindow=time_window,
                status_code=201,
            )
        assert "id" in resp.data
        alert_rule = AlertRule.objects.get(id=resp.data["id"])
        assert resp.data == serialize(alert_rule, self.user)

    def test_no_feature(self):
        self.create_member(
            user=self.user, organization=self.organization, role="owner", teams=[self.team]
        )
        self.login_as(self.user)
        resp = self.get_response(self.organization.slug, self.project.slug)
        assert resp.status_code == 404

    def test_no_perms(self):
        self.create_member(
            user=self.user, organization=self.organization, role="member", teams=[self.team]
        )
        self.login_as(self.user)
        resp = self.get_response(self.organization.slug, self.project.slug)
        assert resp.status_code == 403


class ProjectCombinedRuleIndexEndpointTest(BaseAlertRuleSerializerTest, APITestCase, TestCase):
    def setup_project_and_rules(self):
        self.org = self.create_organization(owner=self.user, name="Rowdy Tiger")
        self.team = self.create_team(organization=self.org, name="Mariachi Band")
        self.project = self.create_project(organization=self.org, teams=[self.team], name="Bengal")
        self.login_as(self.user)
        self.projects = [self.project, self.create_project()]
        self.alert_rule = self.create_alert_rule(
            projects=self.projects, date_added=before_now(minutes=6).replace(tzinfo=pytz.UTC)
        )
        self.other_alert_rule = self.create_alert_rule(
            projects=self.projects, date_added=before_now(minutes=5).replace(tzinfo=pytz.UTC)
        )
        self.issue_rule = self.create_issue_alert_rule(
            data={
                "project": self.project,
                "name": "Issue Rule Test",
                "conditions": [],
                "actions": [],
                "actionMatch": "all",
                "date_added": before_now(minutes=4).replace(tzinfo=pytz.UTC),
            }
        )
        self.yet_another_alert_rule = self.create_alert_rule(
            projects=self.projects, date_added=before_now(minutes=3).replace(tzinfo=pytz.UTC)
        )
        self.combined_rules_url = "/api/0/projects/{0}/{1}/combined-rules/".format(
            self.org.slug, self.project.slug
        )

    def test_invalid_limit(self):
        self.setup_project_and_rules()
        with self.feature("organizations:incidents"):
            request_data = {"limit": "notaninteger"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 400

    def test_limit_higher_than_cap(self):
        pass  # TODO: Make limit a variable, so we can set it low for this test and avoid doing so many DB operations for a not-so-important test.
        # self.setup_project_and_rules()
        # for _ in range(125):
        #     self.create_alert_rule(projects=self.projects)

        # # Test limit above result cap (which is 100), no cursor.
        # with self.feature("organizations:incidents"):
        #     request_data = {"limit": "125"}
        #     response = self.client.get(
        #         path=self.combined_rules_url, data=request_data, content_type="application/json"
        #     )
        # assert response.status_code == 200
        # result = json.loads(response.content)
        # assert len(result) == 100

    def test_limit_higher_than_results_no_cursor(self):
        self.setup_project_and_rules()
        # Test limit above result count (which is 4), no cursor.
        with self.feature("organizations:incidents"):
            request_data = {"limit": "5"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200
        result = json.loads(response.content)
        assert len(result) == 4
        self.assert_alert_rule_serialized(self.yet_another_alert_rule, result[0], skip_dates=True)
        assert result[1]["id"] == six.text_type(self.issue_rule.id)
        assert result[1]["type"] == "rule"
        self.assert_alert_rule_serialized(self.other_alert_rule, result[2], skip_dates=True)
        self.assert_alert_rule_serialized(self.alert_rule, result[3], skip_dates=True)

    def test_limit_as_1_with_paging(self):
        self.setup_project_and_rules()

        # Test Limit as 1, no cursor:
        with self.feature("organizations:incidents"):
            request_data = {"limit": "1"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 1
        self.assert_alert_rule_serialized(self.yet_another_alert_rule, result[0], skip_dates=True)

        links = requests.utils.parse_header_links(
            response.get("link").rstrip(">").replace(">,<", ",<")
        )
        next_cursor = links[1]["cursor"]

        # Test Limit as 1, next page of previous request:
        with self.feature("organizations:incidents"):
            request_data = {"cursor": next_cursor, "limit": "1"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200
        result = json.loads(response.content)
        assert len(result) == 1
        assert result[0]["id"] == six.text_type(self.issue_rule.id)
        assert result[0]["type"] == "rule"

    def test_limit_as_2_with_paging(self):
        self.setup_project_and_rules()

        # Test Limit as 2, no cursor:
        with self.feature("organizations:incidents"):
            request_data = {"limit": "2"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 2
        self.assert_alert_rule_serialized(self.yet_another_alert_rule, result[0], skip_dates=True)
        assert result[1]["id"] == six.text_type(self.issue_rule.id)
        assert result[1]["type"] == "rule"

        links = requests.utils.parse_header_links(
            response.get("link").rstrip(">").replace(">,<", ",<")
        )
        next_cursor = links[1]["cursor"]
        # Test Limit 2, next page of previous request:
        with self.feature("organizations:incidents"):
            request_data = {"cursor": next_cursor, "limit": "2"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 2
        self.assert_alert_rule_serialized(self.other_alert_rule, result[0], skip_dates=True)
        self.assert_alert_rule_serialized(self.alert_rule, result[1], skip_dates=True)

        links = requests.utils.parse_header_links(
            response.get("link").rstrip(">").replace(">,<", ",<")
        )
        next_cursor = links[1]["cursor"]

        # Test Limit 2, next page of previous request - should get no results since there are only 4 total:
        with self.feature("organizations:incidents"):
            request_data = {"cursor": next_cursor, "limit": "2"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 0

    def test_offset_pagination(self):
        self.setup_project_and_rules()

        self.one_alert_rule = self.create_alert_rule(
            projects=self.projects, date_added=before_now(minutes=2).replace(tzinfo=pytz.UTC)
        )
        self.two_alert_rule = self.create_alert_rule(
            projects=self.projects, date_added=before_now(minutes=1).replace(tzinfo=pytz.UTC)
        )
        self.three_alert_rule = self.create_alert_rule(projects=self.projects)

        # Modify 2nd rule to be date of 3rd rule. Second page offset should now be 1, or else we'll get the incorrect results (we should get one_alert_rule on the second page, but without an offset we would get two_alert_rule).
        self.one_alert_rule.date_added = self.two_alert_rule.date_added
        self.one_alert_rule.save()

        with self.feature("organizations:incidents"):
            request_data = {"limit": "2"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 2
        self.assert_alert_rule_serialized(self.three_alert_rule, result[0], skip_dates=True)
        self.assert_alert_rule_serialized(self.one_alert_rule, result[1], skip_dates=True)

        links = requests.utils.parse_header_links(
            response.get("link").rstrip(">").replace(">,<", ",<")
        )
        next_cursor = links[1]["cursor"]
        assert next_cursor.split(":")[1] == "1"  # Assert offset is properly calculated.

        with self.feature("organizations:incidents"):
            request_data = {"cursor": next_cursor, "limit": "2"}
            response = self.client.get(
                path=self.combined_rules_url, data=request_data, content_type="application/json"
            )
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result) == 2

        self.assert_alert_rule_serialized(self.two_alert_rule, result[0], skip_dates=True)
        self.assert_alert_rule_serialized(self.yet_another_alert_rule, result[1], skip_dates=True)
