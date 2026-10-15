import { useEffect, useState } from 'react';
import { apiFetch as fetch } from './api.js';

export default function HpcFiles({ roots, selectedFiles, onToggle, disabled }) {
    const [root, setRoot] = useState(roots[0]?.id ?? '');
    const [path, setPath] = useState('');
    const [offset, setOffset] = useState(0);
    const [listing, setListing] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);

    useEffect(() => {
        if (!root) return;
        const controller = new AbortController();
        setLoading(true);
        setError('');
        setListing(null);
        const query = new URLSearchParams({ root, path, offset: String(offset) });
        fetch(`/hpc-files/?${query}`, { signal: controller.signal })
            .then(async response => {
                const data = await response.json();
                if (!response.ok) throw new Error(data.error ?? 'Unable to list files');
                if (!controller.signal.aborted) setListing(data);
            })
            .catch(error => {
                if (!controller.signal.aborted) setError(error.message);
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [root, path, offset, refresh]);

    const navigate = nextPath => {
        setPath(nextPath);
        setOffset(0);
        setRefresh(value => value + 1);
    };
    const crumbs = path ? path.split('/') : [];

    return (
        <section className="hpc-file-picker">
            <h3>Files on HPC</h3>
            <label htmlFor="hpc-storage-root">Storage location</label>
            <select id="hpc-storage-root" value={root} disabled={disabled || roots.length === 0}
                onChange={event => { setRoot(event.target.value); navigate(''); }}>
                {roots.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
            <nav className="hpc-breadcrumbs" aria-label="HPC file location">
                <button type="button" onClick={() => navigate('')} disabled={disabled}>{root || 'No storage locations'}</button>
                {crumbs.map((name, index) => (
                    <button type="button" key={index} disabled={disabled}
                        onClick={() => navigate(crumbs.slice(0, index + 1).join('/'))}>{name}</button>
                ))}
            </nav>
            {loading && <p role="status">Loading files...</p>}
            {error && <div role="alert"><p>{error}</p>
                <button type="button" onClick={() => setRefresh(value => value + 1)}>Retry</button>
            </div>}
            {listing && (
                <>
                    <div className="hpc-file-table">
                        <table>
                            <thead><tr><th>Select</th><th>Name</th><th>Size (MB)</th></tr></thead>
                            <tbody>
                                {listing.entries.map(entry => (
                                    <tr key={entry.path}>
                                        <td>{entry.kind === 'file' && (
                                            <input type="checkbox" aria-label={`Select ${entry.name}`} disabled={disabled}
                                                checked={selectedFiles.some(file => file.root === root && file.path === entry.path)}
                                                onChange={() => onToggle(entry)} />
                                        )}</td>
                                        <td>{entry.kind === 'directory'
                                            ? <button type="button" className="hpc-directory" disabled={disabled}
                                                onClick={() => navigate(entry.path)}>{entry.name}/</button>
                                            : <span className="hpc-filename">{entry.name}</span>}</td>
                                        <td>{entry.kind === 'file' ? (entry.size / 1000000).toFixed(2) : ''}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {listing.entries.length === 0 && <p>No audio/video files or accessible folders on this page.</p>}
                    <div className="hpc-pagination">
                        <button type="button" disabled={disabled || offset === 0}
                            onClick={() => setOffset(value => Math.max(0, value - 100))}>Previous</button>
                        <button type="button" disabled={disabled || listing.next_offset === null}
                            onClick={() => setOffset(listing.next_offset)}>Next</button>
                    </div>
                </>
            )}
        </section>
    );
}