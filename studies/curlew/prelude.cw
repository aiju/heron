-- The Curlew prelude: compiled with every program (language.md,
-- "The prelude"). Only what a program uses ends up in its code.

infixr 9 .
infixl 9 !!
infixr 8 ^
infixl 7 *, `div`, `mod`, `quot`, `rem`
infixl 6 +, -
infixr 5 :, ++
infix 4 ==, /=, <, <=, >, >=, `elem`, `notElem`
infixl 4 <$>
infixr 3 &&
infixr 2 ||
infixl 1 >>, >>=
infixr 0 $, $!, `seq`

data Bool = False | True deriving (Eq, Ord, Show, Enum)
data Ordering = LT | EQ | GT deriving (Eq, Ord, Show, Enum)
data Maybe a = Nothing | Just a deriving (Eq, Ord, Show)
data Either a b = Left a | Right b deriving (Eq, Ord, Show)

type String = [Char]
type ShowS = String -> String

-- ---- classes

class Eq a where
  (==), (/=) :: a -> a -> Bool
  x /= y = not (x == y)
  x == y = not (x /= y)

class Eq a => Ord a where
  compare :: a -> a -> Ordering
  (<), (<=), (>), (>=) :: a -> a -> Bool
  max, min :: a -> a -> a
  compare x y = if x == y then EQ else if x <= y then LT else GT
  x < y = case compare x y of { LT -> True; _ -> False }
  x <= y = case compare x y of { GT -> False; _ -> True }
  x > y = case compare x y of { GT -> True; _ -> False }
  x >= y = case compare x y of { LT -> False; _ -> True }
  max x y = if x <= y then y else x
  min x y = if x <= y then x else y

class Show a where
  showsPrec :: Int -> a -> ShowS
  show :: a -> String
  showList :: [a] -> ShowS
  showsPrec _ x s = show x ++ s
  show x = showsPrec 0 x ""
  showList ls s = showListWith shows ls s

class Enum a where
  succ, pred :: a -> a
  toEnum :: Int -> a
  fromEnum :: a -> Int
  enumFrom :: a -> [a]
  enumFromThen :: a -> a -> [a]
  enumFromTo :: a -> a -> [a]
  enumFromThenTo :: a -> a -> a -> [a]
  succ x = toEnum (fromEnum x + 1)
  pred x = toEnum (fromEnum x - 1)
  enumFrom x = map toEnum (enumFrom (fromEnum x))
  enumFromThen x y = map toEnum (enumFromThen (fromEnum x) (fromEnum y))
  enumFromTo x y = map toEnum (enumFromTo (fromEnum x) (fromEnum y))
  enumFromThenTo x y z = map toEnum (enumFromThenTo (fromEnum x) (fromEnum y) (fromEnum z))

class Functor f where
  fmap :: (a -> b) -> f a -> f b

class Monad m where
  return :: a -> m a
  (>>=) :: m a -> (a -> m b) -> m b
  (>>) :: m a -> m b -> m b
  m >> k = m >>= \_ -> k

-- ---- Int: one number type, so arithmetic isn't overloaded

(+), (-), (*), div, mod, quot, rem :: Int -> Int -> Int
x + y = primIntAdd x y
x - y = primIntSub x y
x * y = primIntMul x y
x `div` y = primIntDiv x y
x `mod` y = primIntMod x y
x `quot` y = primIntQuot x y
x `rem` y = primIntRem x y

negate :: Int -> Int
negate x = primIntNeg x

abs, signum :: Int -> Int
abs n = if n < 0 then negate n else n
signum n = if n < 0 then -1 else if n == 0 then 0 else 1

subtract :: Int -> Int -> Int
subtract x y = y - x

even, odd :: Int -> Bool
even n = n `rem` 2 == 0
odd n = n `rem` 2 /= 0

divMod, quotRem :: Int -> Int -> (Int, Int)
divMod n d = (n `div` d, n `mod` d)
quotRem n d = (n `quot` d, n `rem` d)

gcd :: Int -> Int -> Int
gcd a b = gcd' (abs a) (abs b)
  where gcd' x 0 = x
        gcd' x y = gcd' y (x `rem` y)

lcm :: Int -> Int -> Int
lcm _ 0 = 0
lcm 0 _ = 0
lcm a b = abs ((a `quot` gcd a b) * b)

(^) :: Int -> Int -> Int
x ^ n = if n < 0 then error "negative exponent" else pow x n
  where pow _ 0 = 1
        pow y k = if even k then pow (y * y) (k `quot` 2) else y * pow y (k - 1)

-- bitwise, on the 30 bits an Int has
andInt, orInt, xorInt, shiftL, shiftR :: Int -> Int -> Int
andInt x y = primIntAnd x y
orInt x y = primIntOr x y
xorInt x y = primIntXor x y
shiftL x n = primIntShl x n
shiftR x n = primIntShr x n

instance Eq Int where
  x == y = primIntEq x y
  x /= y = primIntNe x y

instance Ord Int where
  x < y = primIntLt x y
  x <= y = primIntLe x y
  x > y = primIntGt x y
  x >= y = primIntGe x y
  compare x y = if primIntLt x y then LT else if primIntEq x y then EQ else GT
  max x y = if primIntLe x y then y else x
  min x y = if primIntLe x y then x else y

instance Show Int where
  showsPrec d n r = if n < 0 && d > 6 then '(' : showInt n (')' : r) else showInt n r

instance Enum Int where
  succ x = x + 1
  pred x = x - 1
  toEnum x = x
  fromEnum x = x
  enumFrom x = x : enumFrom (x + 1)
  enumFromTo x y = if x > y then [] else x : enumFromTo (x + 1) y
  enumFromThen x y = x : enumFromThen y (y + y - x)
  enumFromThenTo x y z
    | y >= x = if x > z then [] else x : enumFromThenTo y (y + y - x) z
    | otherwise = if x < z then [] else x : enumFromThenTo y (y + y - x) z

showInt :: Int -> ShowS
showInt n r = if n < 0 then '-' : showNeg n r else showNeg (negate n) r
  where showNeg m s = if m > -10 then intToDigit (negate m) : s
                      else showNeg (m `quot` 10) (intToDigit (negate (m `rem` 10)) : s)

-- ---- Char

ord :: Char -> Int
ord c = primOrd c

chr :: Int -> Char
chr n = primChr n

instance Eq Char where
  c == d = primIntEq (primOrd c) (primOrd d)
  c /= d = primIntNe (primOrd c) (primOrd d)

instance Ord Char where
  c < d = primIntLt (primOrd c) (primOrd d)
  c <= d = primIntLe (primOrd c) (primOrd d)
  c > d = primIntGt (primOrd c) (primOrd d)
  c >= d = primIntGe (primOrd c) (primOrd d)
  compare c d = compare (primOrd c) (primOrd d)

instance Show Char where
  showsPrec _ c r = '\'' : (if c == '\'' then "\\'" ++ r else showLitChar c ('\'' : r))
  showList cs r = '"' : showLitString cs ('"' : r)

instance Enum Char where
  toEnum n = chr n
  fromEnum c = ord c
  enumFrom c = enumFromTo c (chr 255)

isDigit, isSpace, isUpper, isLower, isAlpha, isAlphaNum :: Char -> Bool
isDigit c = c >= '0' && c <= '9'
isSpace c = c == ' ' || c == '\n' || c == '\t' || c == '\r'
isUpper c = c >= 'A' && c <= 'Z'
isLower c = c >= 'a' && c <= 'z'
isAlpha c = isUpper c || isLower c
isAlphaNum c = isAlpha c || isDigit c

toUpper, toLower :: Char -> Char
toUpper c = if isLower c then chr (ord c - 32) else c
toLower c = if isUpper c then chr (ord c + 32) else c

digitToInt :: Char -> Int
digitToInt c
  | isDigit c = ord c - ord '0'
  | c >= 'a' && c <= 'f' = ord c - ord 'a' + 10
  | c >= 'A' && c <= 'F' = ord c - ord 'A' + 10
  | otherwise = error "digitToInt: not a digit"

intToDigit :: Int -> Char
intToDigit n = if n < 10 then chr (ord '0' + n) else chr (ord 'a' + n - 10)

showLitChar :: Char -> ShowS
showLitChar c r
  | c == '\n' = '\\' : 'n' : r
  | c == '\t' = '\\' : 't' : r
  | c == '\\' = '\\' : '\\' : r
  | ord c < 32 || ord c >= 127 = '\\' : showInt (ord c) r
  | otherwise = c : r

showLitString :: String -> ShowS
showLitString [] r = r
showLitString (c:cs) r
  | c == '"' = '\\' : '"' : showLitString cs r
  | otherwise = showLitChar c (showLitString cs r)

-- ---- Bool and the other small types

not :: Bool -> Bool
not True = False
not False = True

(&&), (||) :: Bool -> Bool -> Bool
True && x = x
False && _ = False
True || _ = True
False || x = x

otherwise :: Bool
otherwise = True

instance Eq () where
  _ == _ = True

instance Ord () where
  compare _ _ = EQ

instance Show () where
  showsPrec _ _ r = '(' : ')' : r

maybe :: b -> (a -> b) -> Maybe a -> b
maybe n _ Nothing = n
maybe _ f (Just x) = f x

fromMaybe :: a -> Maybe a -> a
fromMaybe d Nothing = d
fromMaybe _ (Just x) = x

either :: (a -> c) -> (b -> c) -> Either a b -> c
either f _ (Left x) = f x
either _ g (Right y) = g y

-- ---- tuples

fst :: (a, b) -> a
fst (x, _) = x

snd :: (a, b) -> b
snd (_, y) = y

curry :: ((a, b) -> c) -> a -> b -> c
curry f x y = f (x, y)

uncurry :: (a -> b -> c) -> (a, b) -> c
uncurry f p = f (fst p) (snd p)

instance (Eq a, Eq b) => Eq (a, b) where
  (a, b) == (c, d) = a == c && b == d

instance (Ord a, Ord b) => Ord (a, b) where
  compare (a, b) (c, d) = case compare a c of { EQ -> compare b d; o -> o }

instance (Show a, Show b) => Show (a, b) where
  showsPrec _ (a, b) s = '(' : shows a (',' : shows b (')' : s))

instance (Eq a, Eq b, Eq c) => Eq (a, b, c) where
  (a, b, c) == (d, e, f) = a == d && b == e && c == f

instance (Ord a, Ord b, Ord c) => Ord (a, b, c) where
  compare (a, b, c) (d, e, f) = case compare a d of
    EQ -> case compare b e of { EQ -> compare c f; o -> o }
    o -> o

instance (Show a, Show b, Show c) => Show (a, b, c) where
  showsPrec _ (a, b, c) s = '(' : shows a (',' : shows b (',' : shows c (')' : s)))

instance (Eq a, Eq b, Eq c, Eq d) => Eq (a, b, c, d) where
  (a, b, c, d) == (e, f, g, h) = a == e && b == f && c == g && d == h

instance (Ord a, Ord b, Ord c, Ord d) => Ord (a, b, c, d) where
  compare (a, b, c, d) (e, f, g, h) = compare ((a, b), (c, d)) ((e, f), (g, h))

instance (Show a, Show b, Show c, Show d) => Show (a, b, c, d) where
  showsPrec _ (a, b, c, d) s = '(' : shows a (',' : shows b (',' : shows c (',' : shows d (')' : s))))

-- ---- functions

id :: a -> a
id x = x

const :: a -> b -> a
const x _ = x

flip :: (a -> b -> c) -> b -> a -> c
flip f x y = f y x

(.) :: (b -> c) -> (a -> b) -> a -> c
(.) f g x = f (g x)

($), ($!) :: (a -> b) -> a -> b
f $ x = f x
f $! x = x `seq` f x

until :: (a -> Bool) -> (a -> a) -> a -> a
until p f x = if p x then x else until p f (f x)

undefined :: a
undefined = error "undefined"

-- ---- lists

instance Eq a => Eq [a] where
  [] == [] = True
  (x:xs) == (y:ys) = x == y && xs == ys
  _ == _ = False

instance Ord a => Ord [a] where
  compare [] [] = EQ
  compare [] _ = LT
  compare _ [] = GT
  compare (x:xs) (y:ys) = case compare x y of { EQ -> compare xs ys; o -> o }

instance Show a => Show [a] where
  showsPrec _ xs s = showList xs s

shows :: Show a => a -> ShowS
shows x s = showsPrec 0 x s

showChar :: Char -> ShowS
showChar c s = c : s

showString :: String -> ShowS
showString str s = str ++ s

showParen :: Bool -> ShowS -> ShowS
showParen b p s = if b then '(' : p (')' : s) else p s

showListWith :: (a -> ShowS) -> [a] -> ShowS
showListWith _ [] s = '[' : ']' : s
showListWith showx (x:xs) s = '[' : showx x (showl xs)
  where showl [] = ']' : s
        showl (y:ys) = ',' : showx y (showl ys)

instance Functor [] where
  fmap f xs = map f xs

instance Monad [] where
  return x = [x]
  xs >>= f = concatMap f xs

instance Functor Maybe where
  fmap _ Nothing = Nothing
  fmap f (Just x) = Just (f x)

instance Monad Maybe where
  return x = Just x
  Nothing >>= _ = Nothing
  Just x >>= f = f x

(<$>) :: Functor f => (a -> b) -> f a -> f b
f <$> x = fmap f x

mapM :: Monad m => (a -> m b) -> [a] -> m [b]
mapM _ [] = return []
mapM f (x:xs) = f x >>= \y -> mapM f xs >>= \ys -> return (y : ys)

sequence :: Monad m => [m a] -> m [a]
sequence ms = mapM id ms

map :: (a -> b) -> [a] -> [b]
map _ [] = []
map f (x:xs) = f x : map f xs

(++) :: [a] -> [a] -> [a]
[] ++ ys = ys
(x:xs) ++ ys = x : (xs ++ ys)

filter :: (a -> Bool) -> [a] -> [a]
filter _ [] = []
filter p (x:xs) = if p x then x : filter p xs else filter p xs

concat :: [[a]] -> [a]
concat xss = foldr (++) [] xss

concatMap :: (a -> [b]) -> [a] -> [b]
concatMap f [] = []
concatMap f (x:xs) = f x ++ concatMap f xs

head :: [a] -> a
head (x:_) = x
head [] = error "head: empty list"

tail :: [a] -> [a]
tail (_:xs) = xs
tail [] = error "tail: empty list"

last :: [a] -> a
last [x] = x
last (_:xs) = last xs
last [] = error "last: empty list"

init :: [a] -> [a]
init [x] = []
init (x:xs) = x : init xs
init [] = error "init: empty list"

null :: [a] -> Bool
null [] = True
null _ = False

length :: [a] -> Int
length xs = len xs 0
  where len [] n = n
        len (_:ys) n = len ys (n + 1)

(!!) :: [a] -> Int -> a
(x:xs) !! n = if n == 0 then x else xs !! (n - 1)
[] !! _ = error "!!: index too large"

foldr :: (a -> b -> b) -> b -> [a] -> b
foldr _ z [] = z
foldr f z (x:xs) = f x (foldr f z xs)

foldl :: (b -> a -> b) -> b -> [a] -> b
foldl _ z [] = z
foldl f z (x:xs) = foldl f (f z x) xs

foldl' :: (b -> a -> b) -> b -> [a] -> b
foldl' _ z [] = z
foldl' f z (x:xs) = let z' = f z x in z' `seq` foldl' f z' xs

foldr1 :: (a -> a -> a) -> [a] -> a
foldr1 _ [x] = x
foldr1 f (x:xs) = f x (foldr1 f xs)
foldr1 _ [] = error "foldr1: empty list"

foldl1 :: (a -> a -> a) -> [a] -> a
foldl1 f (x:xs) = foldl f x xs
foldl1 _ [] = error "foldl1: empty list"

sum, product :: [Int] -> Int
sum xs = foldl' (+) 0 xs
product xs = foldl' (*) 1 xs

maximum, minimum :: Ord a => [a] -> a
maximum xs = foldl1 max xs
minimum xs = foldl1 min xs

and, or :: [Bool] -> Bool
and [] = True
and (x:xs) = x && and xs
or [] = False
or (x:xs) = x || or xs

any, all :: (a -> Bool) -> [a] -> Bool
any _ [] = False
any p (x:xs) = p x || any p xs
all _ [] = True
all p (x:xs) = p x && all p xs

elem, notElem :: Eq a => a -> [a] -> Bool
elem _ [] = False
elem x (y:ys) = x == y || elem x ys
notElem x ys = not (elem x ys)

lookup :: Eq a => a -> [(a, b)] -> Maybe b
lookup _ [] = Nothing
lookup k ((k', v):rest) = if k == k' then Just v else lookup k rest

reverse :: [a] -> [a]
reverse xs = rev xs []
  where rev [] acc = acc
        rev (y:ys) acc = rev ys (y : acc)

take :: Int -> [a] -> [a]
take n xs = if n <= 0 then [] else case xs of
  [] -> []
  (y:ys) -> y : take (n - 1) ys

drop :: Int -> [a] -> [a]
drop n xs = if n <= 0 then xs else case xs of
  [] -> []
  (_:ys) -> drop (n - 1) ys

splitAt :: Int -> [a] -> ([a], [a])
splitAt n xs = (take n xs, drop n xs)

takeWhile, dropWhile :: (a -> Bool) -> [a] -> [a]
takeWhile _ [] = []
takeWhile p (x:xs) = if p x then x : takeWhile p xs else []
dropWhile _ [] = []
dropWhile p (x:xs) = if p x then dropWhile p xs else x : xs

span, break :: (a -> Bool) -> [a] -> ([a], [a])
span _ [] = ([], [])
span p (x:xs) = if p x then (let (ys, zs) = span p xs in (x : ys, zs)) else ([], x : xs)
break p xs = span (not . p) xs

zip :: [a] -> [b] -> [(a, b)]
zip (x:xs) (y:ys) = (x, y) : zip xs ys
zip _ _ = []

zip3 :: [a] -> [b] -> [c] -> [(a, b, c)]
zip3 (x:xs) (y:ys) (z:zs) = (x, y, z) : zip3 xs ys zs
zip3 _ _ _ = []

zipWith :: (a -> b -> c) -> [a] -> [b] -> [c]
zipWith f (x:xs) (y:ys) = f x y : zipWith f xs ys
zipWith _ _ _ = []

zipWith3 :: (a -> b -> c -> d) -> [a] -> [b] -> [c] -> [d]
zipWith3 f (x:xs) (y:ys) (z:zs) = f x y z : zipWith3 f xs ys zs
zipWith3 _ _ _ _ = []

unzip :: [(a, b)] -> ([a], [b])
unzip xs = (map fst xs, map snd xs)

iterate :: (a -> a) -> a -> [a]
iterate f x = x : iterate f (f x)

repeat :: a -> [a]
repeat x = let xs = x : xs in xs

replicate :: Int -> a -> [a]
replicate n x = take n (repeat x)

cycle :: [a] -> [a]
cycle [] = error "cycle: empty list"
cycle xs = let ys = xs ++ ys in ys

scanl :: (b -> a -> b) -> b -> [a] -> [b]
scanl f z xs = z : (case xs of
  [] -> []
  (y:ys) -> scanl f (f z y) ys)

scanl1 :: (a -> a -> a) -> [a] -> [a]
scanl1 f (x:xs) = scanl f x xs
scanl1 _ [] = []

scanr :: (a -> b -> b) -> b -> [a] -> [b]
scanr _ z [] = [z]
scanr f z (x:xs) = case scanr f z xs of
  qs@(q:_) -> f x q : qs

lines :: String -> [String]
lines "" = []
lines s = let (l, s') = break (\c -> c == '\n') s
          in l : (case s' of
                    [] -> []
                    (_:s'') -> lines s'')

unlines :: [String] -> String
unlines ls = concatMap (\l -> l ++ "\n") ls

words :: String -> [String]
words s = case dropWhile isSpace s of
  "" -> []
  s' -> let (w, s'') = break isSpace s' in w : words s''

unwords :: [String] -> String
unwords [] = ""
unwords [w] = w
unwords (w:ws) = w ++ ' ' : unwords ws

-- ---- from Data.List

sort :: Ord a => [a] -> [a]
sort xs = sortBy compare xs

sortBy :: (a -> a -> Ordering) -> [a] -> [a]
sortBy cmp xs = mergeAll (sequences xs)
  where
    sequences (a:b:rest) = case cmp a b of
      GT -> descending b [a] rest
      _ -> ascending b (\ys -> a : ys) rest
    sequences ys = [ys]
    descending a as (b:bs) | cmp a b == GT = descending b (a:as) bs
    descending a as bs = (a:as) : sequences bs
    ascending a as (b:bs) | cmp a b /= GT = ascending b (\ys -> as (a:ys)) bs
    ascending a as bs = as [a] : sequences bs
    mergeAll [x] = x
    mergeAll ys = mergeAll (mergePairs ys)
    mergePairs (a:b:rest) = merge a b : mergePairs rest
    mergePairs ys = ys
    merge as@(a:as') bs@(b:bs') = case cmp a b of
      GT -> b : merge as bs'
      _ -> a : merge as' bs
    merge [] bs = bs
    merge as [] = as

insert :: Ord a => a -> [a] -> [a]
insert x [] = [x]
insert x (y:ys) = if x <= y then x : y : ys else y : insert x ys

nub :: Eq a => [a] -> [a]
nub [] = []
nub (x:xs) = x : nub (filter (\y -> not (x == y)) xs)

partition :: (a -> Bool) -> [a] -> ([a], [a])
partition p xs = (filter p xs, filter (not . p) xs)

intercalate :: [a] -> [[a]] -> [a]
intercalate _ [] = []
intercalate _ [x] = x
intercalate sep (x:xs) = x ++ sep ++ intercalate sep xs

transpose :: [[a]] -> [[a]]
transpose [] = []
transpose ([]:xss) = transpose xss
transpose ((x:xs):xss) = (x : [h | (h:_) <- xss]) : transpose (xs : [t | (_:t) <- xss])

-- ---- reading numbers

readInt :: String -> Int
readInt s = case dropWhile isSpace s of
  ('-':ds) -> negate (digits ds 0)
  ds -> digits ds 0
  where digits (c:cs) n | isDigit c = digits cs (n * 10 + ord c - ord '0')
        digits _ n = n
