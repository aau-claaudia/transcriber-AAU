import React from 'react';

const TranscriptionStatus = ({ statusText, activeTask, percentageDone, transcribeAndShutdown, serverStopped}) => {

    return (
        <div style={{marginBottom: '1rem'}}>
            { (transcribeAndShutdown && !serverStopped) && (
                <p style={{color: 'var(--accent-indigo)', fontWeight: '600', marginBottom: '0.75rem'}}>
                    💡 The "transcribe and stop" setting is on. The UCloud job will stop when the transcription completes. The browser window can be closed.
                </p>
            )}
            { (transcribeAndShutdown && serverStopped) && (
                <p style={{color: 'var(--accent-emerald)', fontWeight: '600', marginBottom: '0.75rem'}}>
                    ✅ The "transcribe and stop" setting is on. The UCloud job has now stopped.
                </p>
            )}
            <p style={{marginBottom: '1rem', color: 'var(--text-secondary)'}}>{statusText}</p>

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