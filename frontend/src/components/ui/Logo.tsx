import { useId } from 'react'

export default function Logo({ className = 'h-9 w-9' }: { className?: string }) {
    const id = useId().replace(/:/g, '')

    return (
        <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
            <defs>
                <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stopColor="#2dd4e6" />
                    <stop offset="1" stopColor="#1fa2ff" />
                </linearGradient>
            </defs>
            <path d="M3 24 15 7l7 10 4-5 11 12Z" fill={`url(#${id})`} />
            <path d="M3 29q4.2-4 8.5 0t8.5 0 8.5 0 8.5 0" fill="none" stroke={`url(#${id})`} strokeWidth="2.5" strokeLinecap="round" />
            <path d="M3 35q4.2-4 8.5 0t8.5 0 8.5 0 8.5 0" fill="none" stroke={`url(#${id})`} strokeWidth="2.5" strokeLinecap="round" />
        </svg>
    )
}