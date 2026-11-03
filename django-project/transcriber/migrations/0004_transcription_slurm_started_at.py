from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('transcriber', '0003_transcription_scheduler_terminal_seen_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='transcription',
            name='slurm_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]