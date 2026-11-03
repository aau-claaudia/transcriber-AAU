from django.db import models
import uuid

# Create your models here.

class FileUpload(models.Model):
    file = models.FileField(upload_to='UPLOADS/INPUT')

class FileMetaData(models.Model):
    filepath = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255)
    size = models.IntegerField()
    target_path_sym_link = models.CharField(max_length=255, blank=True, null=True)


class Transcription(models.Model):
    class State(models.TextChoices):
        PREPARING = 'preparing', 'Preparing files'
        STAGED = 'staged', 'Files staged'
        SUBMITTING = 'submitting', 'Submitting'
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        CANCELLING = 'cancelling', 'Cancelling'
        CANCELLED = 'cancelled', 'Cancelled'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.CharField(max_length=100)
    language = models.CharField(max_length=32, default='auto')
    resource_profile = models.CharField(max_length=100, default='cpu-test')
    resources = models.JSONField(default=dict)
    input_manifest = models.JSONField(default=list)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PREPARING)
    active_slot = models.PositiveSmallIntegerField(null=True, default=1, unique=True)
    slurm_job_id = models.CharField(max_length=64, blank=True)
    slurm_started_at = models.DateTimeField(null=True, blank=True)
    failure_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    scheduler_terminal_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(state__in=['preparing', 'staged', 'submitting', 'queued', 'running', 'cancelling'], active_slot=1, active_slot__isnull=False)
                    | (models.Q(state__in=['cancelled', 'succeeded', 'failed']) & models.Q(active_slot__isnull=True))
                ),
                name='transcription_active_state',
            ),
        ]