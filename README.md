# Transcriber-AAU

### Slurm result layout

The Slurm runner publishes one flat directory per recording under `MEDIA_ROOT`:

```text
Interview_base_auto/
  data/
    Interview.wav
    edited_output.json
    metadata.json
  TRANSCRIPTIONS/
    Interview_base_en.aud
    Interview_base_en.csv
    ...remaining original worker outputs...
    files.zip
    transcribe.log
    transcriber_output.txt
```

Directory names use `<input stem>_<model>_<requested language>`, adding `_run2`,
`_run3`, etc. when a previous result exists. Original worker filenames and contents
are preserved, including detected-language suffixes and Parakeet's language-free
filenames. Only the separate `data/edited_output.json` copy receives editor IDs.
Inputs in a batch must have distinct stems, including across different extensions.

The normal output set contains nine standard formats and five merged formats,
plus the ZIP and two logs (17 downloadable files). A worker run without merged
outputs is accepted for languages without diarization support; a partially present
merged set is rejected. The worker ZIP and logs describe the whole batch and are
copied into each recording's result directory.

All recordings are prepared in hidden staging before publication. Each complete
recording becomes visible independently when its directory is renamed into place.
The batch completion manifest stays in `JOBS_ROOT/<UUID>/completion.json` and is
written only after all recordings are published. Publication errors roll back the
directories created by that attempt; an abrupt process kill can leave complete
recording directories without a batch completion manifest. Existing results are
never overwritten. This layout replaces the previous UUID-based result layout;
there is no compatibility reader for that development format.

### Setting up the environment for development


Build transcriber docker image
``` bash
export HF_TOKEN='your-token'
docker buildx build \
  --load \
  --secret id=hf_token,env=HF_TOKEN \
  --build-arg TRANSCRIBER_VERSION=1.22 \
  -f worker-image/Dockerfile \
  -t transcriber-sif:1.22 \
  .
```

Build sif image with apptainer
``` bash
../apptainer/bin/apptainer build transcriber-sif_1.22.sif docker-daemon://transcriber-sif:1.22
```

Copy docker image to HPC cluster
``` bash
docker cp \
  "$PWD/worker-image/transcriber-sif_1.22.sif" \
  ondemand:/home/hpcadmin/containers/transcriber-sif_1.22.sif

docker exec ondemand chown 1001:1001 \
  /home/hpcadmin/containers/transcriber-sif_1.22.sif

docker exec ondemand chmod 0644 \
  /home/hpcadmin/containers/transcriber-sif_1.22.sif
```

Create apparmor profile
``` bash
sudoedit /etc/apparmor.d/hpcts-apptainer
```

Use:
profile hpcts-apptainer flags=(unconfined) {
    userns,
}

Load into kernel:
``` bash
sudo apparmor_parser --replace \
  /etc/apparmor.d/hpcts-apptainer
```

apply to service in yaml file:
services:
  cpn01:
    security_opt:
      - apparmor=hpcts-apptainer

reload service:
``` bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.apptainer.yml \
  up -d --no-deps --force-recreate cpn01
```

Once no container uses the custom profile, unload it
``` bash
sudo apparmor_parser --remove /etc/apparmor.d/hpcts-apptainer
```


Example deploy changed UI files:
docker cp /home/nikko/projects/openondemand/hpc-toolset-tutorial/transcriber-AAU/django-project/django-project/settings.py ondemand:/home/hpcadmin/ondemand/dev/transcriber/django-project/settings.py && docker cp /home/nikko/projects/openondemand/hpc-toolset-tutorial/transcriber-AAU/django-project/transcriber/views.py ondemand:/home/hpcadmin/ondemand/dev/transcriber/transcriber/views.py && docker cp /home/nikko/projects/openondemand/hpc-toolset-tutorial/transcriber-AAU/django-project/frontend/build/. ondemand:/home/hpcadmin/ondemand/dev/transcriber/frontend/build/ && docker exec ondemand chown -R 1001:1001 /home/hpcadmin/ondemand/dev/transcriber/frontend/build && docker exec --user 1001:1001 --env HOME=/home/hpcadmin --workdir /home/hpcadmin/ondemand/dev/transcriber ondemand .venv/bin/python manage.py collectstatic --noinput && docker exec --user 1001:1001 ondemand touch /home/hpcadmin/ondemand/dev/transcriber/tmp/restart.txt