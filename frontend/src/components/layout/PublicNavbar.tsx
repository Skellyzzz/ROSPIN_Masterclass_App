import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Logo from '@/components/ui/Logo'

const links = [
    { href: '#features', label: 'Features' },
    { href: '#about', label: 'About' },
]

export default function PublicNavbar() {
    const [open, setOpen] = useState(false)

    return (
        <header className="sticky top-0 z-50 border-b border-white/10 bg-night/80 backdrop-blur">
            <nav
                className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6"
                aria-label="Main"
            >
                <Link to="/" className="flex items-center gap-2.5">
                    <Logo />
                    <span className="font-display text-lg font-bold">
            Dive Spot <span className="text-sky">Finder</span>
          </span>
                </Link>

                <ul className="hidden items-center gap-8 md:flex">
                    {links.map((l) => (
                        <li key={l.href}>
                            <a href={l.href} className="text-white/80 hover:text-white">
                                {l.label}
                            </a>
                        </li>
                    ))}
                </ul>

                <div className="hidden items-center gap-3 md:flex">
                    <Link
                        to="/login"
                        className="rounded-xl border border-white/15 px-4 py-2 font-semibold hover:bg-white/10"
                    >
                        Sign In
                    </Link>
                    <Link
                        to="/signup"
                        className="rounded-xl bg-sky px-4 py-2 font-semibold text-night hover:brightness-110"
                    >
                        Get Started
                    </Link>
                </div>

                <button
                    type="button"
                    className="rounded-lg p-2 hover:bg-white/10 md:hidden"
                    aria-label={open ? 'Close menu' : 'Open menu'}
                    aria-expanded={open}
                    onClick={() => setOpen((v) => !v)}
                >
                    {open ? <X size={24} /> : <Menu size={24} />}
                </button>
            </nav>

            {open && (
                <div className="border-t border-white/10 px-4 pb-4 md:hidden">
                    <ul className="flex flex-col py-2">
                        {links.map((l) => (
                            <li key={l.href}>
                                <a href={l.href} className="block py-3" onClick={() => setOpen(false)}>
                                    {l.label}
                                </a>
                            </li>
                        ))}
                    </ul>
                    <div className="flex flex-col gap-2">
                        <Link to="/login" className="rounded-xl border border-white/15 px-4 py-2.5 text-center font-semibold">
                            Sign In
                        </Link>
                        <Link to="/signup" className="rounded-xl bg-sky px-4 py-2.5 text-center font-semibold text-night">
                            Get Started
                        </Link>
                    </div>
                </div>
            )}
        </header>
    )
}