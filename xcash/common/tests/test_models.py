from django.db.models import ProtectedError
from django.test import TestCase

from chains.models import Wallet


class UndeletableModelTests(TestCase):
    """UndeletableModel 必须同时堵死实例级与批量级两条 ORM 删除路径。

    被测对象是 common.models 的删除防护能力；UndeletableModel 本身是抽象基类、
    无独立表，故借用最简具体子类 chains.Wallet（创建不需要任何必填字段）作为载体，
    这里验证的不是 Wallet 的业务语义。
    """

    def test_instance_delete_is_blocked(self):
        wallet = Wallet.objects.create()
        with self.assertRaises(ProtectedError):
            wallet.delete()
        # 拦截发生在执行 SQL 之前，记录必须原样保留。
        self.assertEqual(Wallet.objects.count(), 1)

    def test_queryset_delete_is_blocked(self):
        # 关键回归点：Django 的 QuerySet.delete() 不走 Model.delete()。
        # 旧实现仅靠模型上的同名 classmethod，形同虚设，批量删除可绕过保护。
        Wallet.objects.create()
        with self.assertRaises(ProtectedError):
            Wallet.objects.all().delete()
        self.assertEqual(Wallet.objects.count(), 1)

    def test_filtered_queryset_delete_is_blocked(self):
        wallet = Wallet.objects.create()
        with self.assertRaises(ProtectedError):
            Wallet.objects.filter(pk=wallet.pk).delete()
        self.assertEqual(Wallet.objects.count(), 1)
