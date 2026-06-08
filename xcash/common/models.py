from django.db import models
from django.db.models import ProtectedError


class UndeletableQuerySet(models.QuerySet):
    """禁止批量删除的 QuerySet。

    Django 的 QuerySet.delete() 既不会调用 Model.delete()，也不会回调模型上的
    任何自定义方法；因此只重写 Model.delete() 时，Model.objects.filter(...).delete()
    会绕过实例级保护直接发出 SQL。批量删除必须在 QuerySet 层拦截才真正生效。
    """

    def delete(self):
        raise ProtectedError("禁止删除.", self)


class UndeletableModel(models.Model):
    """禁止删除的抽象基类模型。

    同时堵死两条 ORM 删除路径：
    - 实例级：obj.delete()
    - 批量级：Model.objects.filter(...).delete()、反向关系 rel.all().delete()

    抽象基类上声明的 manager 会被子类继承，故子类无需各自重复挂载。
    注意：数据库级联删除由 Django 的 Collector 直接执行 SQL，既不走
    Model.delete() 也不走 QuerySet.delete()，无法用 ORM 钩子拦截；如需防止
    级联连带删除，应在外键上使用 on_delete=PROTECT。
    """

    objects = models.Manager.from_queryset(UndeletableQuerySet)()

    class Meta:
        abstract = True  # 抽象基类，自身不建表

    def delete(self, *args, **kwargs):
        raise ProtectedError("禁止删除.", {self})
