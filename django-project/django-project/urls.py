"""
URL configuration for django-project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path
from transcriber.views import (
    upload_file,
    link_files,
    remove_link,
    poll_transcription_status,
    stop_transcription_task,
    index,
    serve_file,
    get_initialization_data,
    get_active_transcription,
    browse_hpc_files,
    get_completed_transcriptions,
    convert_audio,
    edit_transcription_segment,
    get_notes,
    save_note,
    delete_note,
    export_file,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('upload/', upload_file, name='file_upload'),
    path('poll-transcription-status/<uuid:task_id>/', poll_transcription_status, name='poll_transcription_status'),
    path('stop_transcription_task/<uuid:task_id>/', stop_transcription_task, name='stop_transcription_task'),
    path('active-transcription/', get_active_transcription, name='active_transcription'),
    path('hpc-files/', browse_hpc_files, name='hpc_files'),
    path('get-completed-transcriptions/', get_completed_transcriptions, name='get_completed_transcriptions'),
    path('convert-audio/', convert_audio, name='convert_audio'),
    path('edit-transcription-segment/', edit_transcription_segment, name='edit_transcription_segment'),
    path('get-notes/', get_notes, name='get_notes'),
    path('save-note/', save_note, name='save_note'),
    path('delete-note/', delete_note, name='delete_note'),
    path('export-file/', export_file, name='export_file'),
    path('get-initialization-data/', get_initialization_data, name='get_initialization_data'),
    path('link-files/', link_files, name='link_files'),
    path('remove-link/', remove_link, name='remove_link'),
    re_path(r'^.*media/(?P<path>.*)$', serve_file, name='serve_media_file'), # pattern for download
    re_path(r'^work/(?P<path>.*)$', serve_file, name='serve_work_file'), # pattern for download
    re_path(r'^.*$', index, name='index'),  # Catch-all pattern to serve the React app
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)