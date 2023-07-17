from unittest import TestCase, mock

from compose_flow.kube.mixins import KubeMixIn


class KubeMixInTestCase(TestCase):
    def test_get_secret_name_param(self, *mocks):
        """Ensure the name param is used when getting a secret"""
        mixin = KubeMixIn()
        mixin.workflow = mock.Mock(config_name="BAD")
        mixin.namespace = "something"
        mixin.execute = mock.Mock()

        secret_name = "GOODNAME"
        mixin._get_secret(secret_name)

        mixin.execute.assert_called_with(
            f"rancher kubectl get secrets --namespace something -o yaml {secret_name}"
        )
