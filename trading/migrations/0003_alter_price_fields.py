from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trading', '0002_trade'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='price',
            field=models.DecimalField(max_digits=6, decimal_places=4),
        ),
        migrations.AlterField(
            model_name='trade',
            name='price',
            field=models.DecimalField(max_digits=6, decimal_places=4),
        ),
    ]
