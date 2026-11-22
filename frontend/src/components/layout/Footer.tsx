import { Link } from 'react-router-dom'
import Logo from '@/components/ui/Logo'

export default function Footer() {
    return (
        <footer>
            <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 sm:px-6 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-2.5">
                    <Logo className="h-8 w-8" />
                    <span className="font-display font-bold">
            Dive Spot <span className="text-sky">Finder</span>
          </span>
                </div>

                <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 text-white/80">
                    <a href="#features" className="hover:text-white">Features</a>
                    <a href="#about" className="hover:text-white">About</a>
                    <Link to="/login" className="hover:text-white">Sign In</Link>
                    <Link to="/signup" className="hover:text-white">Get Started</Link>
                </nav>
            </div>

            <div className="border-t border-white/10">
                <p className="mx-auto max-w-6xl px-4 py-4 text-sm text-white/60 sm:px-6">
                    © {new Date().getFullYear()} Dive Spot Finder. Spot data and water measurements are estimates; always check conditions in person before jumping.
                </p>
            </div>
        </footer>
    )
}