-- The digits of e, by a spigot over a lazy stream: e = 2.71828...
-- written in the mixed base 1/2, 1/3, 1/4, ...; each digit multiplies
-- the whole remaining tail by 10 and carries back. Lazy streams and Int
-- division.

edigits :: Int -> String
edigits n = '2' : '.' : go n (replicate (n + 10) 1)
  where
    go 0 _ = []
    go k ds = let (c, ds') = carry 2 (map (* 10) ds) in intToDigit c : go (k - 1) ds'
    carry _ [] = (0, [])
    carry base (d:ds) = let (c, ds') = carry (base + 1) ds
                            x = d + c
                        in (x `div` base, x `mod` base : ds')

main input = "e = " ++ edigits 200 ++ "\n"
