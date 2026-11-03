import React from 'react';

const formatDuration = (seconds) => {
    const totalSeconds = Math.ceil(Math.max(0, seconds));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor(totalSeconds % 3600 / 60);
    const remainder = totalSeconds % 60;
    return hours > 0 ? `${hours}h ${minutes}m ${remainder}s` : `${minutes}m ${remainder}s`;
};

const TranscriptionStatus = ({ statusText, activeTask, status = {} }) => {
    const running = status.job_state === 'running';
    const estimated = status.estimated_duration_seconds;
    const elapsed = status.elapsed_seconds;
    const hasElapsed = Number.isFinite(elapsed);
    const hasEstimate = Number.isFinite(estimated) && estimated > 0;
    const showProgress = running && hasElapsed && hasEstimate;
    const percentage = showProgress ? Math.min(90, Math.max(0, elapsed / estimated * 100)) : 0;

    return (
        <div style={{marginBottom: '1rem'}}>
            <p role="status" style={{marginBottom: '1rem', color: status.state === 'FAILURE' ? 'var(--accent-rose)' : 'var(--text-secondary)'}}>{statusText}</p>
            <dl className="transcription-metadata">
                <dt>Slurm job ID</dt>
                <dd>{status.slurm_job_id ?? 'Not assigned yet'}</dd>
                <dt>Started</dt>
                <dd>{status.slurm_started_at
                    ? <time dateTime={status.slurm_started_at}>{new Date(status.slurm_started_at).toLocaleString()}</time>
                    : 'Not started yet'}</dd>
                {hasEstimate && <>
                    <dt>Estimated runtime</dt>
                    <dd>Approximately {formatDuration(estimated)}</dd>
                </>}
                {hasElapsed && <>
                    <dt>Elapsed</dt>
                    <dd>{formatDuration(elapsed)}</dd>
                </>}
                {showProgress && elapsed < estimated && <>
                    <dt>Estimated remaining</dt>
                    <dd>Approximately {formatDuration(estimated - elapsed)}</dd>
                </>}
            </dl>
            {status.job_state === 'queued' && <p>Waiting for resources.</p>}
            {showProgress && (
                <div style={{marginBottom: '1rem'}}>
                    <label htmlFor="transcription-progress">Estimated progress: {Math.floor(percentage)}%</label>
                    <progress id="transcription-progress" className="progress-bar" max={100} value={percentage} style={{width: '100%'}} />
                    {elapsed >= estimated && <p>Taking longer than estimated.</p>}
                </div>
            )}

            <h3>Active transcription file list</h3>
            <div className="table-container">
                <table>
                    <thead>
                    <tr>
                        <th>Name</th>
                        <th>Size (MB)</th>
                        <th>File origin</th>
                    </tr>
                    </thead>
                    <tbody>
                    {activeTask.map((file, index) => (
                        <tr key={index}>
                            <td title={file.name} style={{
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                maxWidth: '200px'}}>
                                {file.name}
                            </td>
                            <td>{(file.size / 1000000).toFixed(2)}</td>
                            <td>{file.source === 'hpc' ? 'HPC storage' : 'Upload'}</td>
                        </tr>
                    ))}
                    </tbody>
                </table>
            </div>

        </div>
    );
};

export default TranscriptionStatus;